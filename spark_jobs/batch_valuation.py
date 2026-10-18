# -*- coding: utf-8 -*-
"""
潍坊市二手房房价预测系统 —— 房源性价比批量打分脚本

思路：
    用已训练好的随机森林 PipelineModel 对 house_info 中**全部房源**做一次批量预测，
    再把「实际挂牌价」与「模型预测价」做差，得到该房源相对同类房源的偏离度：

        deviation_pct = (挂牌价 - 预测价) / 预测价 * 100

    - 负值：挂牌价低于模型预测价 → 相对便宜（性价比高）
    - 正值：挂牌价高于模型预测价 → 相对偏贵

    结果写入 MySQL 的 house_valuation 表，供前端详情页 / 列表页展示。

    说明：这里是「批量离线打分」，不是逐个调用预测接口——1.8 万条逐条调用 Spark
    需要约 2 小时，而批量 transform 只需几秒。

运行示例：
    spark-submit --jars mysql-connector-j-8.0.31.jar batch_valuation.py
"""

import os
import traceback

from pyspark.ml import PipelineModel
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, IntegerType, StringType

# ============================ 可配置常量 ============================
MYSQL_URL = "jdbc:mysql://192.168.100.102:3306/housing_db?useSSL=false&characterEncoding=utf8"
MYSQL_USER = "root"
MYSQL_PASSWORD = "000000"
MYSQL_DRIVER = "com.mysql.cj.jdbc.Driver"

# 估值结果表
VALUATION_TABLE = "house_valuation"

# 模型路径（与 train_rf_model.py 保持一致，可用环境变量覆盖）
RF_MODEL_PATH = os.environ.get("RF_MODEL_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "models", "rf_housing_model"
)

APP_NAME = "HousingBatchValuation"

# 同区域同户型样本数低于该值时，改用区域整体均价兜底（避免小样本均值不稳定）
PEER_MIN_SAMPLES = 20
# ===================================================================


def create_spark_session():
    """创建 SparkSession。"""
    spark = (
        SparkSession.builder
        .appName(APP_NAME)
        .config("spark.sql.shuffle.partitions", "10")
        .getOrCreate()
    )
    print(f"[VAL] SparkSession 已创建，应用名: {APP_NAME}")
    return spark


def load_features(spark):
    """读取 house_info 中模型需要的 7 个特征列以及 id、总价、面积。"""
    print("[VAL] 正在从 MySQL 读取 house_info ...")
    df = (
        spark.read
        .format("jdbc")
        .option("url", MYSQL_URL)
        .option("dbtable", "house_info")
        .option("user", MYSQL_USER)
        .option("password", MYSQL_PASSWORD)
        .option("driver", MYSQL_DRIVER)
        .load()
    )
    df = df.select(
        F.col("id").cast(IntegerType()).alias("id"),
        F.col("square").cast(DoubleType()).alias("square"),
        F.col("room_num").cast(IntegerType()).alias("room_num"),
        F.col("hall_num").cast(IntegerType()).alias("hall_num"),
        F.col("total_floors").cast(IntegerType()).alias("total_floors"),
        F.col("district").cast(StringType()).alias("district"),
        F.col("decoration").cast(StringType()).alias("decoration"),
        F.col("elevator").cast(StringType()).alias("elevator"),
        F.col("total_price").cast(DoubleType()).alias("total_price"),
        F.col("unit_price").cast(DoubleType()).alias("unit_price"),
    )
    # 与训练时保持一致：7 个特征全部非空、总价与面积为正
    df = df.dropna(subset=["square", "room_num", "hall_num", "total_floors",
                           "district", "decoration", "elevator", "total_price"])
    df = df.filter((F.col("total_price") > 0) & (F.col("square") > 0))
    print(f"[VAL] 参与打分的房源数: {df.count()}")
    return df


def score(df, path):
    """
    加载模型并批量预测，计算两套偏离度：

    1. deviation_pct      挂牌价 相对「模型预测价」的偏离（体现机器学习估值）
    2. peer_deviation_pct 挂牌单价 相对「同区域 + 同户型平均单价」的偏离（同类房源基准）

    两套基准互补：模型残差受随机森林向均值回归的特性影响，
    低价房源容易被判成"便宜"；同区域同户型均价则不受该偏差影响，更稳健。
    前端同时展示两个口径，避免单一指标误导。
    """
    print(f"[VAL] 正在加载模型: {path}")
    model = PipelineModel.load(path)

    print("[VAL] 开始批量预测 ...")
    predictions = model.transform(df)

    scored = (
        predictions
        .withColumn("predicted_total_price", F.round(F.col("prediction"), 2))
        .withColumn(
            "predicted_unit_price",
            F.round(F.col("prediction") * 10000 / F.col("square"), 2),
        )
        .withColumn(
            "deviation_pct",
            F.round((F.col("total_price") - F.col("prediction")) / F.col("prediction") * 100, 2),
        )
        .withColumn("actual_total_price", F.round(F.col("total_price"), 2))
    )

    # 同类房源基准：同区域 + 同户型的平均单价
    #   注意：部分组合（如"奎文区 + 5室"）样本很少，均值不稳定，
    #   因此当同户型样本数不足 PEER_MIN_SAMPLES 时，退回用该区域的整体均价兜底。
    peer = (
        df.groupBy("district", "room_num")
        .agg(
            F.count(F.lit(1)).alias("peer_count"),
            F.round(F.avg("unit_price"), 2).alias("peer_unit_price_raw"),
        )
    )
    district_avg = (
        df.groupBy("district")
        .agg(F.round(F.avg("unit_price"), 2).alias("district_unit_price"))
    )
    scored = scored.join(peer, on=["district", "room_num"], how="left")
    scored = scored.join(district_avg, on="district", how="left")
    scored = scored.withColumn(
        "peer_unit_price",
        F.when(F.col("peer_count") >= PEER_MIN_SAMPLES, F.col("peer_unit_price_raw"))
        .otherwise(F.col("district_unit_price")),
    )
    scored = scored.withColumn(
        "peer_deviation_pct",
        F.round(
            (F.col("unit_price") - F.col("peer_unit_price")) / F.col("peer_unit_price") * 100, 2
        ),
    )

    used_fallback = scored.filter(
        (F.col("peer_count") < PEER_MIN_SAMPLES) | F.col("peer_count").isNull()
    ).count()
    print(f"[VAL] 使用区域均价兜底的房源数: {used_fallback}（同户型样本 < {PEER_MIN_SAMPLES} 条）")

    result = (
        scored
        .withColumn("updated_at", F.current_timestamp())
        .select(
            F.col("id").alias("house_id"),
            "predicted_total_price",
            "predicted_unit_price",
            "actual_total_price",
            "deviation_pct",
            "peer_unit_price",
            "peer_deviation_pct",
            "updated_at",
        )
    )
    return result


def print_distribution(result):
    """打印两套偏离度的分位数分布，便于人工确认分档阈值是否合理。"""
    for col_name in ("deviation_pct", "peer_deviation_pct"):
        print(f"[VAL] ===== 偏离度分布（{col_name}）=====")
        row = result.select(
            F.min(col_name).alias("min"),
            F.expr("percentile_approx(%s, 0.05)" % col_name).alias("p05"),
            F.expr("percentile_approx(%s, 0.25)" % col_name).alias("p25"),
            F.expr("percentile_approx(%s, 0.50)" % col_name).alias("p50"),
            F.expr("percentile_approx(%s, 0.75)" % col_name).alias("p75"),
            F.expr("percentile_approx(%s, 0.95)" % col_name).alias("p95"),
            F.max(col_name).alias("max"),
            F.avg(col_name).alias("avg"),
        ).first()
        for key in ("min", "p05", "p25", "p50", "p75", "p95", "max", "avg"):
            print(f"[VAL]   {key:<4} = {row[key]}")


def write_to_mysql(df):
    """以 TRUNCATE + INSERT 方式覆盖写入估值表（保留表结构）。"""
    print(f"[VAL] 正在写入 MySQL 表 `{VALUATION_TABLE}` ...")
    (
        df.write
        .format("jdbc")
        .option("url", MYSQL_URL)
        .option("dbtable", VALUATION_TABLE)
        .option("user", MYSQL_USER)
        .option("password", MYSQL_PASSWORD)
        .option("driver", MYSQL_DRIVER)
        .option("truncate", "true")
        .mode("overwrite")
        .save()
    )
    print(f"[VAL] 表 `{VALUATION_TABLE}` 写入完成。")


def main():
    spark = None
    try:
        spark = create_spark_session()
        df = load_features(spark)
        result = score(df, RF_MODEL_PATH)
        result.cache()
        print_distribution(result)
        write_to_mysql(result)
        print("[VAL] ===== 房源性价比批量打分完成 =====")
    except Exception as exc:  # noqa: BLE001
        print("[VAL][错误] 批量打分失败，请检查模型路径、MySQL 连接与 house_valuation 表是否存在。")
        print(f"[VAL][错误] 详细信息: {exc}")
        traceback.print_exc()
        raise
    finally:
        if spark is not None:
            spark.stop()
            print("[VAL] SparkSession 已关闭。")


if __name__ == "__main__":
    main()
