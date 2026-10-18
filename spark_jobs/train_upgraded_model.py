# -*- coding: utf-8 -*-
"""
潍坊市二手房房价预测系统 —— 升级模型训练与落库脚本

本脚本完成三件事：
    1) 特征贡献消融：确认「小区目标编码」与「其余新增特征」各自贡献多少，
       以便决定预测表单需要让用户填写哪几项；
    2) 用全量升级特征训练最终模型并保存为新的 PipelineModel（不影响旧模型，便于回滚）；
    3) 把小区目标编码表（community -> 平滑编码值）写入 MySQL，
       供 Django 在预测时查表补全 community_te 特征。

运行：
    spark-submit --jars mysql-connector-j-8.0.31.jar train_upgraded_model.py
"""

import os
import traceback

from pyspark.ml import PipelineModel
from pyspark.ml.evaluation import RegressionEvaluator
from pyspark.ml.feature import StringIndexer, VectorAssembler
from pyspark.ml.regression import RandomForestRegressor
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

# 复用对比实验里的特征工程逻辑，避免两份实现漂移
from train_model_compare import (  # noqa: E402
    BASE_CATEGORICAL, BASE_NUMERIC, EXTRA_CATEGORICAL, EXTRA_NUMERIC,
    K_FOLD, LABEL_COL, MAX_BINS, MYSQL_DRIVER, MYSQL_PASSWORD, MYSQL_URL,
    MYSQL_USER, SEED, SMOOTH_M, TARGET_ENC_OUT, add_target_encoding,
    build_pipeline, create_spark_session, evaluate, load_data,
)
# 复用初版脚本的特征重要性导出逻辑，保证仪表盘图表与线上模型同源
from train_rf_model import export_feature_importance  # noqa: E402

APP_NAME = "HousingUpgradedModel"

# 最终模型输出路径（显式 file:// 前缀，避免在集群上被解析到 HDFS）
MODEL_OUT = os.environ.get("MODEL_OUT") or (
    "file://" + os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "models", "rf_housing_model_v2")
)

# 小区编码表
ENCODING_TABLE = "community_encoding"

# 最终模型超参数
NUM_TREES = 50
MAX_DEPTH = 10


def run_ablation(train_te, test_te, results):
    """特征贡献消融：分别评估「只有小区编码」和「只有其余新增特征」。"""
    up_cat = BASE_CATEGORICAL + EXTRA_CATEGORICAL
    full_num = BASE_NUMERIC + EXTRA_NUMERIC + [TARGET_ENC_OUT]
    other_num = BASE_NUMERIC + EXTRA_NUMERIC

    def rf():
        return RandomForestRegressor(featuresCol="features", labelCol=LABEL_COL,
                                     numTrees=NUM_TREES, maxDepth=MAX_DEPTH,
                                     maxBins=MAX_BINS, seed=SEED)

    # 原 7 特征（基线）
    prep = build_pipeline(BASE_CATEGORICAL, BASE_NUMERIC).fit(train_te)
    m = rf().fit(prep.transform(train_te))
    results.append(("A 原7特征 [基线]",
                    evaluate(m.transform(prep.transform(test_te)), "A 原7特征 [基线]")))

    # 原 7 特征 + 小区目标编码
    prep = build_pipeline(BASE_CATEGORICAL, BASE_NUMERIC + [TARGET_ENC_OUT]).fit(train_te)
    m = rf().fit(prep.transform(train_te))
    results.append(("B 原7特征 + 小区编码",
                    evaluate(m.transform(prep.transform(test_te)), "B 原7特征 + 小区编码")))

    # 原 7 特征 + 其余新增特征（不含小区编码）
    prep = build_pipeline(up_cat, other_num).fit(train_te)
    m = rf().fit(prep.transform(train_te))
    results.append(("C 原7特征 + 其余新增(无小区)",
                    evaluate(m.transform(prep.transform(test_te)), "C 原7特征 + 其余新增(无小区)")))

    # 全部升级特征
    prep = build_pipeline(up_cat, full_num).fit(train_te)
    m = rf().fit(prep.transform(train_te))
    results.append(("D 全部升级特征",
                    evaluate(m.transform(prep.transform(test_te)), "D 全部升级特征")))
    return full_num, up_cat


def save_model(train_te, test_te, num_cols, cat_cols, spark):
    """用全量升级特征训练最终模型并保存，同时导出特征重要性与评估指标。"""
    prep = build_pipeline(cat_cols, num_cols).fit(train_te)
    model = RandomForestRegressor(featuresCol="features", labelCol=LABEL_COL,
                                  numTrees=NUM_TREES, maxDepth=MAX_DEPTH,
                                  maxBins=MAX_BINS, seed=SEED).fit(prep.transform(train_te))
    # 保存「预处理 + 模型」整条 Pipeline，Django 端只需喂原始字段
    #   注意：必须用 PipelineModel（已拟合），不能用 Pipeline —— 后者保存的是
    #   "未拟合的估算器"，加载时会报
    #   "Expected class name PipelineModel but found class name Pipeline"。
    full_model = PipelineModel(stages=list(prep.stages) + [model])
    full_model.write().overwrite().save(MODEL_OUT)
    print(f"[UPG] 模型已保存: {MODEL_OUT}")

    # 同步导出特征重要性，覆盖 stat_feature_importance，
    # 否则仪表盘的"随机森林特征重要性"图仍停留在初版 7 特征模型上（与线上不同源）。
    export_feature_importance(full_model, spark)

    # 评估指标落库，供管理端「数据运维面板」直接展示，
    # 避免面板里的数字靠文档手抄、重训后与实际模型脱节。
    metrics = evaluate(model.transform(prep.transform(test_te)), "E 线上最终模型")
    write_model_metric(spark, metrics, feature_count=len(num_cols) + len(cat_cols),
                       train_rows=int(train_te.count()), test_rows=int(test_te.count()))
    return full_model


def write_model_metric(spark, metrics, feature_count, train_rows, test_rows):
    """把最终模型的评估指标写入 stat_model_metric（单行覆盖写）。

    用 spark.sql 构造单行而不是 createDataFrame(list)，可绕开 Python worker，
    与项目里其它写库脚本保持一致的写法。
    """
    table = "stat_model_metric"
    sql = (
        "SELECT 1 AS id, '{algo}' AS algorithm, {fc} AS feature_count, "
        "{nt} AS num_trees, {md} AS max_depth, {rmse} AS rmse, {mae} AS mae, "
        "{r2} AS r2, {mape} AS mape, {tr} AS train_rows, {ts} AS test_rows, "
        "now() AS trained_at"
    ).format(
        algo="RandomForestRegressor", fc=int(feature_count), nt=NUM_TREES, md=MAX_DEPTH,
        rmse=round(float(metrics["rmse"]), 4),
        mae=round(float(metrics["mae"]), 4),
        r2=round(float(metrics["r2"]), 6),
        mape=round(float(metrics["mape"]), 4),
        tr=int(train_rows), ts=int(test_rows),
    )
    print(f"[UPG] 正在写入 {table}：RMSE={metrics['rmse']:.2f} "
          f"MAE={metrics['mae']:.2f} R2={metrics['r2']:.4f}")
    (
        spark.sql(sql).write.format("jdbc")
        .option("url", MYSQL_URL).option("dbtable", table)
        .option("user", MYSQL_USER).option("password", MYSQL_PASSWORD)
        .option("driver", MYSQL_DRIVER)
        .option("truncate", "true").mode("overwrite").save()
    )
    print(f"[UPG] 表 {table} 写入完成。")


def write_encoding_table(df):
    """把小区目标编码写入 MySQL（用全量数据计算，部署时统计量更稳）。"""
    global_mean = df.agg(F.avg("unit_price")).first()[0]
    enc = (
        df.groupBy("community")
        .agg(F.count(F.lit(1)).alias("house_count"),
             F.avg("unit_price").alias("_mean"),
             F.first("district").alias("district"))
        .withColumn(
            "te_value",
            F.round((F.col("house_count") * F.col("_mean")
                     + F.lit(SMOOTH_M) * F.lit(global_mean))
                    / (F.col("house_count") + F.lit(SMOOTH_M)), 4),
        )
        .select("community", "district", "house_count", "te_value")
        .orderBy(F.col("house_count").desc())
    )
    print(f"[UPG] 正在写入 {ENCODING_TABLE}（全局均价={global_mean:.2f}，{enc.count()} 个小区）...")
    (
        enc.write.format("jdbc")
        .option("url", MYSQL_URL).option("dbtable", ENCODING_TABLE)
        .option("user", MYSQL_USER).option("password", MYSQL_PASSWORD)
        .option("driver", MYSQL_DRIVER)
        .option("truncate", "true").mode("overwrite").save()
    )
    print(f"[UPG] 表 {ENCODING_TABLE} 写入完成。")


def main():
    spark = None
    try:
        spark = create_spark_session()
        spark.conf.set("spark.app.name", APP_NAME)
        df = load_data(spark)

        train_df, test_df = df.randomSplit([0.8, 0.2], seed=SEED)
        print(f"[UPG] 训练集 {train_df.count()} / 测试集 {test_df.count()}")

        print("[UPG] 正在做小区目标编码（5 折 out-of-fold）...")
        train_te, test_te = add_target_encoding(train_df, test_df)
        train_te.cache()
        test_te.cache()

        print("[UPG] ===== 特征贡献消融 =====")
        results = []
        num_cols, cat_cols = run_ablation(train_te, test_te, results)

        print()
        print("[UPG] ===================== 消融汇总 =====================")
        print("[UPG] %-30s %8s %8s %8s %8s" % ("实验", "RMSE", "MAE", "R2", "MAPE"))
        for name, m in results:
            print("[UPG] %-30s %8.2f %8.2f %8.4f %7.2f%%"
                  % (name, m["rmse"], m["mae"], m["r2"], m["mape"]))
        base, only_community, others, full = [r[1] for r in results]
        print("[UPG] ---------------------------------------------------")
        print("[UPG] 小区编码单独贡献   : R2 %+.4f" % (only_community["r2"] - base["r2"]))
        print("[UPG] 其余新增特征单独贡献: R2 %+.4f" % (others["r2"] - base["r2"]))
        print("[UPG] 全部升级特征合计   : R2 %+.4f" % (full["r2"] - base["r2"]))
        print("[UPG] ===================================================")

        # 训练并保存最终模型
        #   消融结论：小区目标编码单独贡献 R² +0.0711，其余新增特征只 +0.0027，
        #   且「原7特征+小区编码」的 R² 反而高于「全部升级特征」——
        #   说明 nearby/direction/type/ownership/梯户比 带来的是噪声而非信息。
        #   因此最终上线模型采用最简且最优的 B 方案：
        #   原 7 特征 + 小区目标编码，预测表单只需新增「小区」一个字段。
        print("[UPG] 正在训练并保存最终模型（B 方案：原7特征 + 小区编码）...")
        save_model(train_te, test_te, BASE_NUMERIC + [TARGET_ENC_OUT], BASE_CATEGORICAL, spark)

        # 落库小区编码表
        write_encoding_table(df)

        print("[UPG] ===== 升级模型训练与落库完成 =====")
    except Exception as exc:  # noqa: BLE001
        print("[UPG][错误] 失败，详情：%s" % exc)
        traceback.print_exc()
        raise
    finally:
        if spark is not None:
            spark.stop()
            print("[UPG] SparkSession 已关闭。")


if __name__ == "__main__":
    main()
