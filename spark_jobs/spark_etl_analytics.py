# -*- coding: utf-8 -*-
"""
潍坊市二手房房价预测系统 —— Spark ETL 与统计指标计算脚本

整体流程：
    1. 从 HDFS 读取原始 CSV（sh_data.csv）
    2. 数据清洗：剔除关键字段为空 / 非法的记录，并做强类型转换
    3. 使用 UDF + 正则从 size、floor 字段抽取派生特征
    4. 使用 SparkSQL 计算 4 项统计指标（区域 / 装修 / 户型 / 热门小区 Top20）
    5. 通过 JDBC 将明细与统计结果写入 MySQL（house_info + 4 张 stat 表）

运行示例（需自行准备 mysql-connector-j 驱动 jar）：
    spark-submit --jars mysql-connector-j-8.0.33.jar spark_etl_analytics.py
"""

import os
import re
import traceback

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, DoubleType, StringType

# ============================ 可配置常量 ============================
# 原始数据在 HDFS 上的位置。
# 这里使用相对路径，Spark 会依据 core-site.xml 的 fs.defaultFS 自动解析
# （本集群为 hdfs://hadoop102:8020），换集群无需改代码；
# 也可用环境变量 HDFS_CSV_PATH 覆盖为完整 URI。
HDFS_CSV_PATH = os.environ.get("HDFS_CSV_PATH", "/housing/raw/sh_data.csv")

# MySQL 连接配置（JDBC）
MYSQL_URL = "jdbc:mysql://192.168.100.102:3306/housing_db?useSSL=false&characterEncoding=utf8"
MYSQL_USER = "root"
MYSQL_PASSWORD = "000000"
MYSQL_DRIVER = "com.mysql.cj.jdbc.Driver"

# Spark 应用名
APP_NAME = "HousingSparkETL"
# ===================================================================


def create_spark_session():
    """创建并返回 SparkSession。"""
    spark = (
        SparkSession.builder
        .appName(APP_NAME)
        .config("spark.sql.shuffle.partitions", "10")
        .getOrCreate()
    )
    print(f"[ETL] SparkSession 已创建，应用名: {APP_NAME}")
    return spark


def read_raw_data(spark):
    """读取 HDFS 上的原始 CSV 数据，返回 DataFrame。"""
    print(f"[ETL] 正在读取原始数据: {HDFS_CSV_PATH}")
    df = (
        spark.read
        .option("header", True)
        .option("encoding", "UTF-8")
        .csv(HDFS_CSV_PATH)
    )
    print(f"[ETL] 原始数据行数: {df.count()}")
    return df


def clean_data(df):
    """
    数据清洗：
      1. 将各字段强制转换为目标类型；
      2. 剔除 total_price / unit_price / square 为空或 <= 0 的记录；
      3. 剔除 district 为空的记录。
    """
    print("[ETL] 开始数据清洗 ...")
    cleaned = (
        df.select(
            F.col("id").cast(IntegerType()).alias("id"),
            F.col("title").cast(StringType()).alias("title"),
            F.col("total_price").cast(DoubleType()).alias("total_price"),
            F.col("unit_price").cast(DoubleType()).alias("unit_price"),
            F.col("square").cast(DoubleType()).alias("square"),
            F.col("size").cast(StringType()).alias("size"),
            F.col("floor").cast(StringType()).alias("floor"),
            F.col("direction").cast(StringType()).alias("direction"),
            F.col("type").cast(StringType()).alias("type"),
            F.col("district").cast(StringType()).alias("district"),
            F.col("nearby").cast(StringType()).alias("nearby"),
            F.col("community").cast(StringType()).alias("community"),
            F.col("decoration").cast(StringType()).alias("decoration"),
            F.col("elevator").cast(StringType()).alias("elevator"),
            F.col("elevatorNum").cast(StringType()).alias("elevatorNum"),
            F.col("ownership").cast(StringType()).alias("ownership"),
        )
        # 剔除关键数值字段为空或 <= 0 的记录
        .filter(
            F.col("total_price").isNotNull() & (F.col("total_price") > 0)
            & F.col("unit_price").isNotNull() & (F.col("unit_price") > 0)
            & F.col("square").isNotNull() & (F.col("square") > 0)
        )
        # 剔除区域为空的记录
        .filter(F.col("district").isNotNull() & (F.trim(F.col("district")) != ""))
    )
    print(f"[ETL] 清洗后数据行数: {cleaned.count()}")
    return cleaned


# ============================ 特征抽取 UDF ============================
@F.udf(returnType=IntegerType())
def _udf_room_num(size):
    """从 size 中抽取室数，例如 '2室2厅1厨1卫' -> 2，抽取不到返回 0。"""
    if not size:
        return 0
    matched = re.search(r"(\d+)室", size)
    return int(matched.group(1)) if matched else 0


@F.udf(returnType=IntegerType())
def _udf_hall_num(size):
    """从 size 中抽取厅数，例如 '2室2厅1厨1卫' -> 2，抽取不到返回 0。"""
    if not size:
        return 0
    matched = re.search(r"(\d+)厅", size)
    return int(matched.group(1)) if matched else 0


@F.udf(returnType=IntegerType())
def _udf_total_floors(floor):
    """从 floor 中抽取总楼层数，例如 '中楼层 (共11层)' -> 11，抽取不到返回 0。"""
    if not floor:
        return 0
    matched = re.search(r"共(\d+)层", floor)
    return int(matched.group(1)) if matched else 0


@F.udf(returnType=StringType())
def _udf_floor_type(floor):
    """从 floor 中抽取楼层位置（高楼层/中楼层/低楼层），抽取不到返回空字符串。"""
    if not floor:
        return ""
    for keyword in ("高楼层", "中楼层", "低楼层"):
        if keyword in floor:
            return keyword
    return ""


def extract_features(df):
    """使用 UDF 从 size、floor 字段派生 room_num / hall_num / total_floors / floor_type。"""
    print("[ETL] 开始特征抽取（room_num / hall_num / total_floors / floor_type）...")
    return (
        df.withColumn("room_num", _udf_room_num(F.col("size")))
          .withColumn("hall_num", _udf_hall_num(F.col("size")))
          .withColumn("total_floors", _udf_total_floors(F.col("floor")))
          .withColumn("floor_type", _udf_floor_type(F.col("floor")))
    )


def build_house_info_df(df):
    """整理出与 MySQL house_info 表字段、顺序完全一致的 DataFrame。"""
    return df.select(
        F.col("id").cast(IntegerType()).alias("id"),
        F.col("title").cast(StringType()).alias("title"),
        F.col("total_price").cast(DoubleType()).alias("total_price"),
        F.col("unit_price").cast(DoubleType()).alias("unit_price"),
        F.col("square").cast(DoubleType()).alias("square"),
        F.col("size").cast(StringType()).alias("size"),
        F.col("room_num").cast(IntegerType()).alias("room_num"),
        F.col("hall_num").cast(IntegerType()).alias("hall_num"),
        F.col("floor").cast(StringType()).alias("floor"),
        F.col("floor_type").cast(StringType()).alias("floor_type"),
        F.col("total_floors").cast(IntegerType()).alias("total_floors"),
        F.col("direction").cast(StringType()).alias("direction"),
        F.col("type").cast(StringType()).alias("type"),
        F.col("district").cast(StringType()).alias("district"),
        F.col("nearby").cast(StringType()).alias("nearby"),
        F.col("community").cast(StringType()).alias("community"),
        F.col("decoration").cast(StringType()).alias("decoration"),
        F.col("elevator").cast(StringType()).alias("elevator"),
        F.col("elevatorNum").cast(StringType()).alias("elevatorNum"),
        F.col("ownership").cast(StringType()).alias("ownership"),
    )


def write_to_mysql(df, table):
    """
    通过 JDBC 将 DataFrame 覆盖写入指定的 MySQL 表。

    注意：这里使用 mode("overwrite") + option("truncate", "true")。
    若只用 mode("overwrite")，Spark 会 DROP 再 CREATE，导致 schema.sql 里
    定义的主键、索引与字段类型（VARCHAR/DECIMAL）全部丢失。
    加上 truncate 后改为 TRUNCATE + INSERT，表结构保持 schema.sql 的权威定义。
    """
    print(f"[ETL] 正在写入 MySQL 表 `{table}`（行数={df.count()}）...")
    (
        df.write
        .format("jdbc")
        .option("url", MYSQL_URL)
        .option("dbtable", table)
        .option("user", MYSQL_USER)
        .option("password", MYSQL_PASSWORD)
        .option("driver", MYSQL_DRIVER)
        .option("truncate", "true")
        .mode("overwrite")
        .save()
    )
    print(f"[ETL] 表 `{table}` 写入完成。")


def main():
    spark = None
    try:
        spark = create_spark_session()

        # 1. 读取 + 清洗 + 特征抽取
        raw_df = read_raw_data(spark)
        clean_df = clean_data(raw_df)
        feature_df = extract_features(clean_df)

        # 注册临时视图，供 SparkSQL 聚合使用
        feature_df.createOrReplaceTempView("house_clean")

        # 2. 明细表写入（列名与 house_info 完全一致）
        house_info_df = build_house_info_df(feature_df)
        write_to_mysql(house_info_df, "house_info")

        # 3. 区域维度统计：district, house_count, avg_total_price, avg_unit_price, avg_square
        stat_district_df = spark.sql(
            """
            SELECT district,
                   COUNT(*)                     AS house_count,
                   ROUND(AVG(total_price), 2)   AS avg_total_price,
                   ROUND(AVG(unit_price), 2)    AS avg_unit_price,
                   ROUND(AVG(square), 2)        AS avg_square
            FROM house_clean
            GROUP BY district
            """
        )
        write_to_mysql(stat_district_df, "stat_district")

        # 4. 装修维度统计：decoration, house_count, avg_unit_price
        stat_decoration_df = spark.sql(
            """
            SELECT decoration,
                   COUNT(*)                   AS house_count,
                   ROUND(AVG(unit_price), 2)  AS avg_unit_price
            FROM house_clean
            WHERE decoration IS NOT NULL AND TRIM(decoration) != ''
            GROUP BY decoration
            """
        )
        write_to_mysql(stat_decoration_df, "stat_decoration")

        # 5. 户型维度统计：room_num, house_count, avg_unit_price（仅统计 room_num > 0）
        stat_room_type_df = spark.sql(
            """
            SELECT room_num,
                   COUNT(*)                   AS house_count,
                   ROUND(AVG(unit_price), 2)  AS avg_unit_price
            FROM house_clean
            WHERE room_num > 0
            GROUP BY room_num
            ORDER BY room_num
            """
        )
        write_to_mysql(stat_room_type_df, "stat_room_type")

        # 6. 热门小区 Top20：community, district, house_count, avg_total_price, avg_unit_price
        stat_community_top_df = spark.sql(
            """
            SELECT community,
                   district,
                   COUNT(*)                     AS house_count,
                   ROUND(AVG(total_price), 2)   AS avg_total_price,
                   ROUND(AVG(unit_price), 2)    AS avg_unit_price
            FROM house_clean
            WHERE community IS NOT NULL AND TRIM(community) != ''
            GROUP BY community, district
            ORDER BY house_count DESC
            LIMIT 20
            """
        )
        write_to_mysql(stat_community_top_df, "stat_community_top")

        print("[ETL] ===== 全部 ETL 与统计任务执行完成 =====")

    except Exception as exc:  # noqa: BLE001 —— 顶层兜底，输出友好提示
        print("[ETL][错误] 任务执行失败，请检查 HDFS 路径、Spark 环境与 MySQL 连接配置。")
        print(f"[ETL][错误] 详细信息: {exc}")
        traceback.print_exc()
        raise
    finally:
        if spark is not None:
            spark.stop()
            print("[ETL] SparkSession 已关闭。")


if __name__ == "__main__":
    main()
