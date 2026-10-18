# -*- coding: utf-8 -*-
"""
潍坊市二手房房价预测系统 —— 模型对比实验脚本

目的：
    1) 消融对比：量化「特征工程升级」带来多少提升（原 7 特征 vs 升级特征）
    2) 模型对比：线性回归 / 随机森林 / 梯度提升树（GBT）横向比较
    3) 产出可用于论文「模型优化与评估」章节的对比数据

特征工程升级点：
    - 新增类别特征：nearby(商圈)、direction(朝向)、type(建筑类型)、ownership(产权)
    - 新增数值特征：elevator_ratio(梯户比户数)、avg_room_area(每室平均面积)
    - 小区(community)用「平滑目标编码」转成数值特征（K 折 out-of-fold，防数据泄漏）

评估口径：与线上模型保持一致（RMSE / MAE / R²，80/20 划分，seed=42）

运行：
    spark-submit --jars mysql-connector-j-8.0.31.jar train_model_compare.py
"""

import re
import traceback

from pyspark.ml import Pipeline
from pyspark.ml.evaluation import RegressionEvaluator
from pyspark.ml.feature import StringIndexer, VectorAssembler
from pyspark.ml.regression import GBTRegressor, LinearRegression, RandomForestRegressor
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, IntegerType, StringType

# ============================ 配置 ============================
MYSQL_URL = "jdbc:mysql://192.168.100.102:3306/housing_db?useSSL=false&characterEncoding=utf8"
MYSQL_USER = "root"
MYSQL_PASSWORD = "000000"
MYSQL_DRIVER = "com.mysql.cj.jdbc.Driver"

APP_NAME = "HousingModelCompare"
LABEL_COL = "total_price"
SEED = 42

# 原始 7 特征
BASE_NUMERIC = ["square", "room_num", "hall_num", "total_floors"]
BASE_CATEGORICAL = ["district", "decoration", "elevator"]

# 升级新增
EXTRA_CATEGORICAL = ["nearby", "direction", "type", "ownership"]
EXTRA_NUMERIC = ["elevator_ratio", "avg_room_area"]
TARGET_ENC_OUT = "community_te"

# 目标编码参数
K_FOLD = 5
SMOOTH_M = 20.0

# 决策树的分箱上限：Spark 默认 maxBins=32，而 nearby(商圈) 有 65 个取值，
# 超过上限会直接抛 IllegalArgumentException，因此需要显式提高。
# 所有树模型统一用同一个值，保证消融对比公平。
MAX_BINS = 128
# =============================================================

CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def create_spark_session():
    spark = (
        SparkSession.builder
        .appName(APP_NAME)
        .config("spark.sql.shuffle.partitions", "10")
        .getOrCreate()
    )
    print(f"[CMP] SparkSession 已创建: {APP_NAME}")
    return spark


def load_data(spark):
    """加载数据并做基础清洗 + 衍生特征。"""
    print("[CMP] 正在读取 house_info ...")
    df = (
        spark.read.format("jdbc")
        .option("url", MYSQL_URL).option("dbtable", "house_info")
        .option("user", MYSQL_USER).option("password", MYSQL_PASSWORD)
        .option("driver", MYSQL_DRIVER).load()
    )

    df = df.select(
        F.col("square").cast(DoubleType()).alias("square"),
        F.col("room_num").cast(IntegerType()).alias("room_num"),
        F.col("hall_num").cast(IntegerType()).alias("hall_num"),
        F.col("total_floors").cast(IntegerType()).alias("total_floors"),
        F.col("district").cast(StringType()).alias("district"),
        F.col("decoration").cast(StringType()).alias("decoration"),
        F.col("elevator").cast(StringType()).alias("elevator"),
        F.col("nearby").cast(StringType()).alias("nearby"),
        F.col("direction").cast(StringType()).alias("direction"),
        F.col("type").cast(StringType()).alias("type"),
        F.col("ownership").cast(StringType()).alias("ownership"),
        F.col("elevatorNum").cast(StringType()).alias("elevatorNum"),
        F.col("community").cast(StringType()).alias("community"),
        F.col("unit_price").cast(DoubleType()).alias("unit_price"),
        F.col("total_price").cast(DoubleType()).alias(LABEL_COL),
    )

    all_cols = (BASE_NUMERIC + BASE_CATEGORICAL + EXTRA_CATEGORICAL
                + ["elevatorNum", "community", "unit_price", LABEL_COL])
    before = df.count()
    df = df.dropna(subset=[c for c in all_cols if c != "elevatorNum"])
    df = df.filter((F.col(LABEL_COL) > 0) & (F.col("square") > 0) & (F.col("room_num") > 0))
    print(f"[CMP] 清洗: {before} -> {df.count()} 行")

    # 衍生特征
    udf_ratio = F.udf(_parse_elevator_ratio, IntegerType())
    df = (
        df.withColumn("elevator_ratio", udf_ratio(F.col("elevatorNum")))
        .withColumn("avg_room_area", F.round(F.col("square") / F.col("room_num"), 2))
    )
    # 梯户比缺失用中位数兜底
    median_ratio = df.approxQuantile("elevator_ratio", [0.5], 0.01)[0] or 2
    df = df.fillna({"elevator_ratio": int(median_ratio)})
    print(f"[CMP] 梯户比缺失用中位数兜底: {median_ratio}")
    return df


def _parse_elevator_ratio(value):
    """从「一梯三户」这类文本里取出户数（3）。"""
    if not value:
        return None
    m = re.search(r"([一二两三四五六七八九十]+)\s*户", str(value))
    if not m:
        return None
    s = m.group(1)
    if s == "十":
        return 10
    if "十" in s:
        head, _, tail = s.partition("十")
        return (CN_NUM.get(head, 1) if head else 1) * 10 + (CN_NUM.get(tail, 0) if tail else 0)
    return CN_NUM.get(s)


def smoothing_stats(source_df, key_col, value_col, global_mean, out_col, m=SMOOTH_M):
    """平滑目标编码： (n*mean + m*global) / (n + m)"""
    return (
        source_df.groupBy(key_col)
        .agg(F.count(F.lit(1)).alias("_cnt"), F.avg(value_col).alias("_mean"))
        .withColumn(out_col, (F.col("_cnt") * F.col("_mean") + F.lit(m) * F.lit(global_mean))
                    / (F.col("_cnt") + F.lit(m)))
        .select(key_col, out_col)
    )


def add_target_encoding(train_df, test_df, key_col="community",
                        value_col="unit_price", out_col=TARGET_ENC_OUT,
                        k=K_FOLD, seed=SEED):
    """
    小区目标编码（防泄漏）：
      - 训练集内部做 K 折 out-of-fold：每折用「其它折」的统计量编码，
        避免某条样本用自己的价格去编码自己；
      - 测试集用「训练集全量」的统计量编码。
    """
    global_mean = train_df.agg(F.avg(value_col)).first()[0]
    print(f"[CMP] 目标编码全局均值({value_col}) = {global_mean:.2f}")

    train_fold = train_df.withColumn("_fold", (F.rand(seed) * k).cast("int")).cache()
    parts = []
    for i in range(k):
        src = train_fold.filter(F.col("_fold") != i)
        tgt = train_fold.filter(F.col("_fold") == i)
        stats = smoothing_stats(src, key_col, value_col, global_mean, out_col)
        parts.append(tgt.join(stats, on=key_col, how="left").drop("_fold"))

    encoded_train = parts[0]
    for p in parts[1:]:
        encoded_train = encoded_train.unionByName(p)

    stats_full = smoothing_stats(train_df, key_col, value_col, global_mean, out_col)
    encoded_test = test_df.join(stats_full, on=key_col, how="left")

    # 未见过的类别用全局均值兜底
    encoded_train = encoded_train.fillna({out_col: global_mean})
    encoded_test = encoded_test.fillna({out_col: global_mean})
    train_fold.unpersist()
    return encoded_train, encoded_test


def build_pipeline(cat_cols, num_cols):
    """StringIndexer(类别) + VectorAssembler(全部特征) 的预处理 Pipeline。"""
    idx_cols = [f"{c}_idx" for c in cat_cols]
    indexers = [StringIndexer(inputCol=c, outputCol=f"{c}_idx", handleInvalid="keep")
                for c in cat_cols]
    assembler = VectorAssembler(inputCols=num_cols + idx_cols, outputCol="features",
                                handleInvalid="keep")
    return Pipeline(stages=indexers + [assembler])


def evaluate(pred, name):
    """计算 RMSE / MAE / R²，并附带相对误差参考。"""
    metrics = {}
    for m in ("rmse", "mae", "r2"):
        ev = RegressionEvaluator(labelCol=LABEL_COL, predictionCol="prediction", metricName=m)
        metrics[m] = ev.evaluate(pred)
    # MAPE：平均绝对百分比误差（房价跨量级，相对误差更直观）
    mape = pred.select(
        F.avg(F.abs(F.col("prediction") - F.col(LABEL_COL)) / F.col(LABEL_COL) * 100).alias("mape")
    ).first()["mape"]
    metrics["mape"] = mape
    print("[CMP] %-34s RMSE=%6.2f  MAE=%6.2f  R2=%.4f  MAPE=%.2f%%"
          % (name, metrics["rmse"], metrics["mae"], metrics["r2"], metrics["mape"]))
    return metrics


def run_experiment(train_df, test_df, cat_cols, num_cols, model, name, results):
    """跑一次「特征预处理 + 模型训练 + 评估」。"""
    prep = build_pipeline(cat_cols, num_cols).fit(train_df)
    tr = prep.transform(train_df)
    te = prep.transform(test_df)
    fitted = model.fit(tr)
    metrics = evaluate(fitted.transform(te), name)
    results.append((name, metrics))


def main():
    spark = None
    try:
        spark = create_spark_session()
        df = load_data(spark)

        # 划分（与线上保持一致）
        train_df, test_df = df.randomSplit([0.8, 0.2], seed=SEED)
        print(f"[CMP] 训练集 {train_df.count()} / 测试集 {test_df.count()}")

        # 目标编码
        print("[CMP] 正在做小区目标编码（5 折 out-of-fold）...")
        train_te, test_te = add_target_encoding(train_df, test_df)
        train_te.cache()
        test_te.cache()

        results = []

        # ---------- A. 基线：原 7 特征 + RF(50,10) ----------
        run_experiment(train_df, test_df, BASE_CATEGORICAL, BASE_NUMERIC,
                       RandomForestRegressor(featuresCol="features", labelCol=LABEL_COL,
                                             numTrees=50, maxDepth=10, maxBins=MAX_BINS,
                                             seed=SEED),
                       "A 原7特征 + RF(50,10) [基线]", results)

        # ---------- B. 升级特征 + RF(50,10)：隔离"特征工程"贡献 ----------
        up_cat = BASE_CATEGORICAL + EXTRA_CATEGORICAL
        up_num = BASE_NUMERIC + EXTRA_NUMERIC + [TARGET_ENC_OUT]
        run_experiment(train_te, test_te, up_cat, up_num,
                       RandomForestRegressor(featuresCol="features", labelCol=LABEL_COL,
                                             numTrees=50, maxDepth=10, maxBins=MAX_BINS,
                                             seed=SEED),
                       "B 升级特征 + RF(50,10)", results)

        # ---------- C. 升级特征 + RF(100,10)：隔离"树数量"贡献 ----------
        run_experiment(train_te, test_te, up_cat, up_num,
                       RandomForestRegressor(featuresCol="features", labelCol=LABEL_COL,
                                             numTrees=100, maxDepth=10, maxBins=MAX_BINS,
                                             seed=SEED),
                       "C 升级特征 + RF(100,10)", results)

        # ---------- D. 升级特征 + 线性回归（算法对比基线） ----------
        run_experiment(train_te, test_te, up_cat, up_num,
                       LinearRegression(featuresCol="features", labelCol=LABEL_COL,
                                        maxIter=100, regParam=0.1, elasticNetParam=0.0),
                       "D 升级特征 + 线性回归", results)

        # ---------- E. 升级特征 + GBT（梯度提升） ----------
        run_experiment(train_te, test_te, up_cat, up_num,
                       GBTRegressor(featuresCol="features", labelCol=LABEL_COL,
                                    maxIter=100, maxDepth=6, stepSize=0.1,
                                    maxBins=MAX_BINS, seed=SEED),
                       "E 升级特征 + GBT(100,6)", results)

        # ---------- 汇总 ----------
        print()
        print("[CMP] ===================== 对比汇总 =====================")
        print("[CMP] %-34s %8s %8s %8s %8s" % ("实验", "RMSE", "MAE", "R2", "MAPE"))
        base = results[0][1]
        for name, m in results:
            print("[CMP] %-34s %8.2f %8.2f %8.4f %7.2f%%"
                  % (name, m["rmse"], m["mae"], m["r2"], m["mape"]))
        print("[CMP] ====================================================")
        best = max(results, key=lambda x: x[1]["r2"])
        print("[CMP] R² 最高的实验: %s (R2=%.4f, 相比基线提升 %.4f)"
              % (best[0], best[1]["r2"], best[1]["r2"] - base["r2"]))
        print("[CMP] 说明：以上指标口径与线上模型一致（80/20、seed=42、RMSE/MAE/R²）")

    except Exception as exc:  # noqa: BLE001
        print("[CMP][错误] 对比实验失败。")
        print(f"[CMP][错误] 详细信息: {exc}")
        traceback.print_exc()
        raise
    finally:
        if spark is not None:
            spark.stop()
            print("[CMP] SparkSession 已关闭。")


if __name__ == "__main__":
    main()
