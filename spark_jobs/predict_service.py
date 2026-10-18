# -*- coding: utf-8 -*-
"""
潍坊市二手房房价预测系统 —— 在线预测服务模块

设计要点（重要）：
    本模块会被 Django 直接 import，因此**顶层绝对不能创建 SparkSession 或加载模型**，
    否则每次启动 Django 都会付出昂贵的初始化代价甚至报错。
    所有重资源（SparkSession / PipelineModel）均采用【懒加载 + 模块级缓存】。

对外接口：
    - predict_house_price(features: dict) -> dict          # 主预测函数（可能抛异常）
    - predict_house_price_safe(features: dict) -> dict|None # 安全版，异常时返回 None
    - is_model_ready() -> bool                             # 判断模型文件是否就绪
"""

import ctypes
import os
import sys

from pyspark.sql import SparkSession
from pyspark.ml import PipelineModel

# ============================ 可配置常量 ============================
# 模型路径：升级版模型（原 7 特征 + 小区目标编码），可用环境变量 RF_MODEL_PATH 覆盖
RF_MODEL_PATH = os.environ.get("RF_MODEL_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "models", "rf_housing_model_v2"
)

# Spark master（默认本地模式）
SPARK_MASTER = os.environ.get("SPARK_MASTER", "local[*]")
APP_NAME = "HousingPredictService"

# 小区目标编码表的数据库连接（与 Django settings 保持一致的可覆盖默认值）
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = os.environ.get("DB_PORT", "3306")
DB_NAME = os.environ.get("DB_NAME", "housing_db")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "000000")

# 编码表不可用时的最后兜底值（即训练时观察到的全局平均单价，元/㎡）
DEFAULT_COMMUNITY_TE = 7167.18
# ===================================================================

# 模块级缓存（懒加载核心）：初始为 None，首次调用时才真正创建/加载
_spark = None
_model = None
_encoding = None

# Windows 下预加载的 hadoop.dll 句柄（保持引用，避免被 GC 卸载）
_WIN_DLL_HANDLES = []


def _prepare_windows_hadoop():
    """
    在 Windows 上让 PySpark 能加载 Hadoop 本地库（否则 PipelineModel.load 会抛
    UnsatisfiedLinkError: NativeIO$Windows.access0）。

    需要三个文件，均位于 <spark_jobs>/tools/hadoop/bin/：
      1. winutils.exe    —— Hadoop Shell 通过 HADOOP_HOME 定位；
      2. hadoop.dll      —— JVM 原需 java.library.path 才能找到，这里改用 ctypes 预加载，
                            既避免设置 JAVA_TOOL_OPTIONS，也能安全支持含中文的工程路径；
      3. msvcr120.dll    —— hadoop.dll 依赖的 VC++2013 运行库，与 hadoop.dll 同目录即可。
    """
    if os.name != "nt":
        return
    hadoop_home = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "hadoop")
    bin_dir = os.path.join(hadoop_home, "bin")
    dll_path = os.path.join(bin_dir, "hadoop.dll")
    if not os.path.isfile(dll_path):
        return

    os.environ.setdefault("HADOOP_HOME", hadoop_home)
    # 固定本地回环地址，避免 Spark 解析主机名（Windows 上解析慢且易超时）
    os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    try:
        os.add_dll_directory(bin_dir)
    except (AttributeError, OSError):
        pass
    try:
        _WIN_DLL_HANDLES.append(ctypes.CDLL(dll_path))
        print("[PREDICT] 已预加载 Windows Hadoop 本地库: %s" % dll_path)
    except OSError as exc:
        print("[PREDICT][警告] 预加载 hadoop.dll 失败: %s" % exc)


def _get_spark():
    """
    获取（懒加载）全局唯一的 SparkSession。

    使用 getOrCreate()，若进程中已存在 SparkSession 则直接复用，
    避免重复初始化。
    """
    global _spark
    if _spark is None:
        _prepare_windows_hadoop()
        # 让 Spark 的 Python worker 复用当前解释器：
        # 否则 worker 会去 PATH 里找 `python`，可能拿到与本环境不兼容的版本，
        # 报 "Python worker failed to connect back"。
        os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
        os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
        _spark = (
            SparkSession.builder
            .appName(APP_NAME)
            .master(SPARK_MASTER)
            .config("spark.ui.enabled", "false")
            .config("spark.python.worker.reuse", "true")
            .getOrCreate()
        )
    return _spark


def _resolve_model_path(path: str) -> str:
    """
    归一化模型路径，保证指向本地磁盘。

    在 Linux 集群上 Hadoop 通常把 fs.defaultFS 配成 HDFS，此时 PipelineModel.load
    会把普通绝对路径（如 /opt/...）解析成 hdfs://... 而找不到本地文件；
    因此这里显式加 file:// 前缀。Windows 下默认文件系统就是本地，保持原样即可
    （也避免非 ASCII 路径被 URI 编码后出错）。
    """
    if "://" in path or os.name == "nt":
        return path
    return "file://" + path


def _get_model():
    """
    获取（懒加载）全局唯一的 PipelineModel。

    首次调用时从 RF_MODEL_PATH 加载并缓存到模块级变量 _model。
    """
    global _model
    if _model is None:
        _model = PipelineModel.load(_resolve_model_path(RF_MODEL_PATH))
    return _model


def is_model_ready() -> bool:
    """检测模型目录是否存在，供 Django 判断是否需要降级。"""
    return os.path.isdir(RF_MODEL_PATH)


def _load_encoding():
    """
    一次性把小区目标编码表读入内存（1750 行，开销可忽略），避免每次预测查库。

    同时预先算好「各区域平均编码值」，用于小区未命中时的兜底。
    """
    global _encoding
    if _encoding is not None:
        return _encoding

    import pymysql  # 局部导入，避免未安装 pymysql 时影响模块导入

    conn = pymysql.connect(
        host=DB_HOST, port=int(DB_PORT), user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, charset="utf8mb4", connect_timeout=5,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT community, te_value, district FROM community_encoding")
            rows = cur.fetchall()
    finally:
        conn.close()

    mapping = {r[0]: float(r[1]) for r in rows if r[0] is not None and r[1] is not None}
    dist_sum, dist_cnt = {}, {}
    for _name, te, district in rows:
        if district:
            dist_sum[district] = dist_sum.get(district, 0.0) + float(te)
            dist_cnt[district] = dist_cnt.get(district, 0) + 1
    district_avg = {d: dist_sum[d] / dist_cnt[d] for d in dist_sum}
    global_avg = (sum(mapping.values()) / len(mapping)) if mapping else DEFAULT_COMMUNITY_TE

    _encoding = {"map": mapping, "district": district_avg, "global": global_avg}
    print(f"[PREDICT] 小区编码表已载入: {len(mapping)} 个小区, 全局均值={global_avg:.2f}")
    return _encoding


def resolve_community_te(community, district) -> float:
    """
    解析小区目标编码值，按 小区 -> 区域 -> 全局 的优先级逐级兜底。

    对应训练时 train_upgraded_model.py 里写入的 community_encoding 表。
    """
    try:
        enc = _load_encoding()
    except Exception as exc:  # noqa: BLE001 —— 编码表不可用时不应中断预测
        print(f"[PREDICT][警告] 读取小区编码表失败，使用兜底值: {exc}")
        return DEFAULT_COMMUNITY_TE

    key = (community or "").strip()
    if key and key in enc["map"]:
        return enc["map"][key]
    dist = (district or "").strip()
    if dist and dist in enc["district"]:
        return enc["district"][dist]
    return enc["global"] or DEFAULT_COMMUNITY_TE


def _build_input_df(spark, features: dict):
    """
    构造单行输入 DataFrame。

    刻意用 spark.sql 构造，而不是 spark.createDataFrame([row], schema)：
    后者会生成持有 Python 侧数据的 ParallelCollectionRDD，取值时必须拉起
    Spark 的 Python worker，在 Windows 上每个请求要多花约 20 秒。
    用 SQL 构造出的计划完全在 JVM 侧执行，不依赖 Python worker。
    """
    def _quote(value):
        # 转义单引号，避免拼接 SQL 出错
        return str(value).replace("'", "''")

    sql = (
        "SELECT '{district}' AS district, "
        "{square} AS square, "
        "{room_num} AS room_num, "
        "{hall_num} AS hall_num, "
        "{total_floors} AS total_floors, "
        "'{decoration}' AS decoration, "
        "'{elevator}' AS elevator, "
        "{community_te} AS community_te"
    ).format(
        district=_quote(features.get("district") or ""),
        square=float(features.get("square") or 0.0),
        room_num=int(features.get("room_num") or 0),
        hall_num=int(features.get("hall_num") or 0),
        total_floors=int(features.get("total_floors") or 0),
        decoration=_quote(features.get("decoration") or ""),
        elevator=_quote(features.get("elevator") or ""),
        # 小区目标编码：由 predict_house_price 解析后传入，缺失时逐级兜底
        community_te=float(features.get("community_te") or DEFAULT_COMMUNITY_TE),
    )
    return spark.sql(sql)


def _read_prediction_via_jvm(model, input_df) -> float:
    """
    直接在 JVM 侧取出预测值，绕开 DataFrame.first() / collect() 的 Python 回传路径。

    纯 py4j 调用，不启动 Python worker，单次通常只要几十毫秒。
    """
    out_jdf = model.transform(input_df)._jdf
    columns = [str(name) for name in out_jdf.columns()]
    index = columns.index("prediction")
    rows = out_jdf.collectAsList()
    if rows.isEmpty():
        raise RuntimeError("预测结果为空")
    return float(rows.get(0).getDouble(index))


def predict_house_price(features: dict) -> dict:
    """
    根据房屋特征预测总价与单价。

    入参 features 需要包含以下键：
        district(str), square(float), room_num(int),
        hall_num(int), total_floors(int), decoration(str), elevator(str)
    可选键：
        community(str) —— 小区名称。提供后会用「小区目标编码」提升精度；
                          未提供或表中查不到时，自动按 区域 -> 全局 逐级兜底。

    返回：
        {"predicted_total_price": float, "predicted_unit_price": float,
         "community_te": float, "community_matched": bool}
        总价单位为万元，单价单位为元/㎡，均保留 2 位小数。
    """
    spark = _get_spark()
    model = _get_model()

    square = float(features.get("square") or 0.0)

    # 解析小区目标编码（升级模型新增的特征）
    community = (features.get("community") or "").strip()
    community_te = resolve_community_te(community, features.get("district"))
    matched = False
    try:
        matched = bool(community) and community in _load_encoding()["map"]
    except Exception:  # noqa: BLE001
        matched = False

    input_features = dict(features)
    input_features["community_te"] = community_te
    input_df = _build_input_df(spark, input_features)

    # 优先走 JVM 直取（毫秒级）；异常时退回常规 Python 取值路径（慢但兼容）
    try:
        prediction = _read_prediction_via_jvm(model, input_df)
    except Exception:
        result_row = model.transform(input_df).select("prediction").first()
        prediction = float(result_row["prediction"]) if result_row else 0.0

    predicted_total_price = round(prediction, 2)
    # 单价 = 总价(万元) * 10000 / 面积；面积为 0 时单价返回 0
    if square > 0:
        predicted_unit_price = round(predicted_total_price * 10000 / square, 2)
    else:
        predicted_unit_price = 0.0

    return {
        "predicted_total_price": float(predicted_total_price),
        "predicted_unit_price": float(predicted_unit_price),
        "community_te": float(community_te),
        "community_matched": matched,
    }


def warm_up():
    """
    预热预测服务：提前创建 SparkSession、加载模型并跑一次示例推理。

    这样首个真实请求不必再等 JVM 冷启动（约十几秒）。
    异常一律吞掉，预热失败只是首次请求慢一些，不影响功能。
    """
    try:
        sample = {
            "district": "奎文区", "square": 100.0, "room_num": 3,
            "hall_num": 1, "total_floors": 18, "decoration": "精装", "elevator": "有",
            "community": "",
        }
        # 走与真实请求完全一致的链路，顺带把小区编码表也载入内存
        predict_house_price(sample)
        print("[PREDICT] 预热完成，预测服务已就绪")
    except Exception as exc:  # noqa: BLE001 —— 预热失败不应影响启动
        print("[PREDICT][警告] 预热失败，将在首次请求时再初始化: %s" % exc)


def predict_house_price_safe(features: dict):
    """
    安全版预测：捕获所有异常。

    模型不可用或预测失败时返回 None，交由 Django 做降级处理，
    绝不向上层抛出异常。
    """
    try:
        if not is_model_ready():
            return None
        return predict_house_price(features)
    except Exception as exc:  # noqa: BLE001 —— 对外接口需绝对安全
        # 仅打印日志，不抛出
        print(f"[PREDICT][警告] 预测失败，返回 None: {exc}")
        return None


if __name__ == "__main__":
    # 本地自测：使用潍坊市常见参数打印预测结果
    sample = {
        "district": "奎文区",
        "square": 110.0,
        "room_num": 3,
        "hall_num": 2,
        "total_floors": 18,
        "decoration": "精装",
        "elevator": "有",
        "community": "",
    }

    print("模型是否就绪:", is_model_ready())
    print("输入特征:", sample)
    print("预测结果:", predict_house_price_safe(sample))
