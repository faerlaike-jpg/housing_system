# -*- coding: utf-8 -*-
"""
潍坊市二手房房价预测系统 —— 随机森林回归模型训练脚本

流程：
    1. 从 MySQL 的 house_info 表读取明细数据（JDBC）
    2. 选取数值特征与类别特征，并做缺失值处理
    3. 使用 PySpark ML 的 Pipeline 串联：
         StringIndexer x3  ->  VectorAssembler  ->  RandomForestRegressor
       保存整条 PipelineModel（推理时可直接传入原始字符串列）
    4. 按 8:2 划分训练/测试集，输出 RMSE / MAE / R2 三项指标
    5. 将 PipelineModel 保存到本地磁盘（可通过环境变量 RF_MODEL_PATH 覆盖）

运行示例（需自行准备 mysql-connector-j 驱动 jar）：
    spark-submit --jars mysql-connector-j-8.0.33.jar train_rf_model.py
"""

import os
import shutil
import traceback

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, DoubleType, StringType

from pyspark.ml import Pipeline
from pyspark.ml.feature import StringIndexer, VectorAssembler
from pyspark.ml.regression import RandomForestRegressor
from pyspark.ml.evaluation import RegressionEvaluator

# ============================ 可配置常量 ============================
# MySQL 连接配置（JDBC）
MYSQL_URL = "jdbc:mysql://192.168.100.102:3306/housing_db?useSSL=false&characterEncoding=utf8"
MYSQL_USER = "root"
MYSQL_PASSWORD = "000000"
MYSQL_DRIVER = "com.mysql.cj.jdbc.Driver"

# 特征重要性写入的目标表
IMPORTANCE_TABLE = "stat_feature_importance"

APP_NAME = "HousingRandomForestTrain"

# 模型保存路径（可用环境变量 RF_MODEL_PATH 覆盖）：
#   默认 = 本脚本同级目录下的 models/rf_housing_model。
#   注意：Spark 的 save() 走 Hadoop FileSystem，绝对路径会用 core-site.xml 的
#   fs.defaultFS 解析，因此运行在 Hadoop 集群上时默认会落到 HDFS
#   （本集群实际保存为 hdfs://hadoop102:8020/opt/module/housing/models/rf_housing_model），
#   这也符合"模型导出保存到 HDFS"的设计目标。
#   如需强制保存到本地磁盘，请在路径前加 file://，例如：
#       RF_MODEL_PATH=file:///opt/module/housing/models/rf_housing_model
RF_MODEL_PATH = os.environ.get("RF_MODEL_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "models", "rf_housing_model"
)

# 随机种子（保证训练/划分可复现）
SEED = 42

# 数值型特征列
NUMERIC_FEATURES = ["square", "room_num", "hall_num", "total_floors"]
# 类别型特征列（需要先 StringIndexer 编码）
CATEGORICAL_FEATURES = ["district", "decoration", "elevator"]
# 标签列
LABEL_COL = "total_price"
# ===================================================================


def create_spark_session():
    """创建并返回 SparkSession。"""
    spark = (
        SparkSession.builder
        .appName(APP_NAME)
        .config("spark.sql.shuffle.partitions", "10")
        .getOrCreate()
    )
    print(f"[TRAIN] SparkSession 已创建，应用名: {APP_NAME}")
    return spark


def load_data(spark):
    """从 MySQL house_info 表读取数据，并完成类型转换 / 缺失值处理。"""
    print("[TRAIN] 正在从 MySQL 读取 house_info ...")
    raw_df = (
        spark.read
        .format("jdbc")
        .option("url", MYSQL_URL)
        .option("dbtable", "house_info")
        .option("user", MYSQL_USER)
        .option("password", MYSQL_PASSWORD)
        .option("driver", MYSQL_DRIVER)
        .load()
    )

    # 选取需要的列并强转类型
    df = raw_df.select(
        F.col("square").cast(DoubleType()).alias("square"),
        F.col("room_num").cast(IntegerType()).alias("room_num"),
        F.col("hall_num").cast(IntegerType()).alias("hall_num"),
        F.col("total_floors").cast(IntegerType()).alias("total_floors"),
        F.col("district").cast(StringType()).alias("district"),
        F.col("decoration").cast(StringType()).alias("decoration"),
        F.col("elevator").cast(StringType()).alias("elevator"),
        F.col("total_price").cast(DoubleType()).alias("total_price"),
    )

    # 缺失值处理 + 过滤非法标签
    before = df.count()
    df = df.dropna(subset=NUMERIC_FEATURES + CATEGORICAL_FEATURES + [LABEL_COL])
    df = df.filter(F.col("total_price") > 0)
    after = df.count()
    print(f"[TRAIN] 数据加载完成：清洗前 {before} 行 -> 清洗后 {after} 行")
    return df


def build_pipeline():
    """
    构建完整的 Pipeline：
        3 个 StringIndexer + 1 个 VectorAssembler + 1 个 RandomForestRegressor

    说明：把特征工程与模型一起放进 Pipeline 并整体保存，
        推理时 PipelineModel 可以直接接收原始字符串列，无需手动编码。
    """
    indexers = [
        StringIndexer(inputCol=col, outputCol=f"{col}_idx", handleInvalid="keep")
        for col in CATEGORICAL_FEATURES
    ]

    assembler = VectorAssembler(
        inputCols=[
            "square", "room_num", "hall_num", "total_floors",
            "district_idx", "decoration_idx", "elevator_idx",
        ],
        outputCol="features",
        handleInvalid="keep",
    )

    rf = RandomForestRegressor(
        featuresCol="features",
        labelCol=LABEL_COL,
        numTrees=50,
        maxDepth=10,
        seed=SEED,
    )

    # 顺序不能乱：先编码 -> 再拼特征向量 -> 再喂给随机森林
    return Pipeline(stages=indexers + [assembler, rf])


def evaluate(predictions):
    """计算并打印 RMSE / MAE / R2 三项回归指标。"""
    metrics = {}
    for metric_name in ("rmse", "mae", "r2"):
        evaluator = RegressionEvaluator(
            labelCol=LABEL_COL, predictionCol="prediction", metricName=metric_name
        )
        metrics[metric_name] = evaluator.evaluate(predictions)

    print("[TRAIN] ===== 模型评估结果（测试集）=====")
    print(f"[TRAIN] RMSE = {metrics['rmse']:.4f}")
    print(f"[TRAIN] MAE  = {metrics['mae']:.4f}")
    print(f"[TRAIN] R2   = {metrics['r2']:.4f}")
    return metrics


def save_model(model, path):
    """保存 PipelineModel；若本地目录已存在则先安全删除。"""
    print(f"[TRAIN] 正在保存模型到: {path}")
    # 若目标为已存在的本地目录，先安全删除，避免 save 报 “path already exists”
    if os.path.exists(path):
        try:
            shutil.rmtree(path, ignore_errors=True)
            print("[TRAIN] 已清理旧的模型目录。")
        except Exception as exc:  # noqa: BLE001
            print(f"[TRAIN][警告] 清理旧模型目录失败（忽略）: {exc}")

    model.write().overwrite().save(path)
    print("[TRAIN] 模型保存完成。")


def export_feature_importance(model, spark):
    """
    提取随机森林的特征重要性，打印排名并写入 MySQL 的 stat_feature_importance 表。

    VectorAssembler 的输入顺序即特征顺序，其中类别特征编码后列名为 xxx_idx，
    这里统一去掉 _idx 后缀，方便前端映射成中文名。
    """
    print("[TRAIN] ===== 特征重要性（Feature Importance）=====")
    rf_model = model.stages[-1]
    input_cols = model.stages[-2].getInputCols()
    scores = rf_model.featureImportances.toArray()

    pairs = sorted(
        ((name.replace("_idx", ""), float(score)) for name, score in zip(input_cols, scores)),
        key=lambda item: item[1],
        reverse=True,
    )
    for name, score in pairs:
        print(f"[TRAIN]   {name:<14} {score:.4f}")

    importance_df = spark.createDataFrame(pairs, ["feature", "importance"])
    (
        importance_df.write
        .format("jdbc")
        .option("url", MYSQL_URL)
        .option("dbtable", IMPORTANCE_TABLE)
        .option("user", MYSQL_USER)
        .option("password", MYSQL_PASSWORD)
        .option("driver", MYSQL_DRIVER)
        .option("truncate", "true")
        .mode("overwrite")
        .save()
    )
    print(f"[TRAIN] 特征重要性已写入 MySQL 表 `{IMPORTANCE_TABLE}`。")


def main():
    spark = None
    try:
        spark = create_spark_session()

        # 1. 加载数据
        df = load_data(spark)

        # 2. 划分训练集 / 测试集（8:2）
        train_df, test_df = df.randomSplit([0.8, 0.2], seed=SEED)
        print(f"[TRAIN] 训练集行数: {train_df.count()}，测试集行数: {test_df.count()}")

        # 3. 构建并训练 Pipeline
        pipeline = build_pipeline()
        print("[TRAIN] 开始训练随机森林模型（numTrees=50, maxDepth=10）...")
        model = pipeline.fit(train_df)

        # 4. 预测与评估
        predictions = model.transform(test_df)
        evaluate(predictions)

        # 5. 输出特征重要性并写入 MySQL（供可视化仪表盘使用）
        export_feature_importance(model, spark)

        # 6. 保存 PipelineModel
        save_model(model, RF_MODEL_PATH)

        print("[TRAIN] ===== 模型训练与保存全部完成 =====")

    except Exception as exc:  # noqa: BLE001 —— 顶层兜底，输出友好提示
        print("[TRAIN][错误] 模型训练失败，请检查 MySQL 数据、Spark 环境与磁盘权限。")
        print(f"[TRAIN][错误] 详细信息: {exc}")
        traceback.print_exc()
        raise
    finally:
        if spark is not None:
            spark.stop()
            print("[TRAIN] SparkSession 已关闭。")


if __name__ == "__main__":
    main()
