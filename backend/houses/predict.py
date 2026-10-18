"""
房价预测服务封装。

优先尝试调用 Spark 侧 predict_service.predict_house_price_safe；
若 Spark 环境不可用（未安装 pySpark / 模型未训练 / 导入失败 / 返回空），
则优雅降级为基于 stat_district 统计数据的估算，保证接口永不因预测异常而失败。

对外统一返回：
    {"predicted_total_price": float, "predicted_unit_price": float, "engine": "spark"|"statistic"}
"""
import sys
from pathlib import Path

from django.conf import settings
from django.db.models import Avg

from analysis.models import StatDistrict
from houses.models import CommunityEncoding, HouseInfo

# spark_jobs 目录绝对路径：<project_root>/spark_jobs（BASE_DIR 为 backend 目录）
SPARK_JOBS_DIR = str(Path(settings.BASE_DIR).parent / "spark_jobs")

# 装修 / 电梯 / 楼层 的简易系数修正（统计降级时使用）
_DECORATION_FACTOR = {"精装": 1.07, "简装": 1.00, "毛坯": 0.95}


def _call_spark(params):
    """尝试调用 Spark 预测服务，成功返回 dict，否则返回 None。"""
    try:
        if SPARK_JOBS_DIR not in sys.path:
            sys.path.insert(0, SPARK_JOBS_DIR)
        from predict_service import predict_house_price_safe  # noqa: WPS433

        # 兼容两种调用签名：整体入参 / 关键字展开
        try:
            result = predict_house_price_safe(params)
        except TypeError:
            result = predict_house_price_safe(
                district=params.get("district"),
                square=params.get("square"),
                room_num=params.get("room_num"),
                hall_num=params.get("hall_num"),
                total_floors=params.get("total_floors"),
                decoration=params.get("decoration"),
                elevator=params.get("elevator"),
            )

        if not result:
            return None
        total = result.get("predicted_total_price", result.get("total_price"))
        unit = result.get("predicted_unit_price", result.get("unit_price"))
        if total is None or unit is None:
            return None
        return {
            "predicted_total_price": round(float(total), 2),
            "predicted_unit_price": round(float(unit), 2),
            "engine": "spark",
            # 升级模型的小区编码命中情况，供前端提示"已按小区校准"
            "community_matched": bool(result.get("community_matched")),
        }
    except Exception:
        return None


def warm_up():
    """
    预热 Spark 预测服务（供 Django 启动时后台线程调用）。

    提前完成 JVM 启动与模型加载，使第一个预测请求不必等待冷启动。
    Spark 环境不可用时静默返回，不影响系统启动。
    """
    try:
        if SPARK_JOBS_DIR not in sys.path:
            sys.path.insert(0, SPARK_JOBS_DIR)
        from predict_service import warm_up as _warm_up  # noqa: WPS433

        _warm_up()
    except Exception:
        pass


def _call_statistic(district, square, decoration, elevator, total_floors, community=None):
    """基于区域统计均价的估算（Spark 不可用时的降级方案）。"""
    base = None
    matched = False

    # 优先用小区级均价（community_encoding 表，与升级模型口径一致）
    if community:
        enc = CommunityEncoding.objects.filter(community=community).first()
        if enc is not None and enc.te_value is not None:
            base = float(enc.te_value)
            matched = True

    if base is None:
        stat = StatDistrict.objects.filter(district=district).first()
        if stat is not None and stat.avg_unit_price is not None:
            base = float(stat.avg_unit_price)
    if base is None:
        agg = HouseInfo.objects.aggregate(u=Avg("unit_price"))
        base = float(agg.get("u") or 0)

    factor = 1.0
    # 装修修正
    if decoration:
        for key, ratio in _DECORATION_FACTOR.items():
            if key in decoration:
                factor *= ratio
                break
    # 电梯修正
    if elevator:
        if "有" in elevator:
            factor *= 1.03
        elif "无" in elevator:
            factor *= 0.98
    # 楼层总量修正（高层/多层小幅度调整）
    if total_floors:
        try:
            tf = int(float(total_floors))
            if tf >= 18:
                factor *= 1.02
            elif tf <= 6:
                factor *= 0.99
        except (TypeError, ValueError):
            pass

    unit_price = base * factor
    total_price = unit_price * float(square) / 10000.0  # 单价(元/㎡)*面积(㎡) -> 万元
    return {
        "predicted_total_price": round(total_price, 2),
        "predicted_unit_price": round(unit_price, 2),
        "engine": "statistic",
        "community_matched": matched,
    }


def predict_price(district, square, room_num=None, hall_num=None,
                  total_floors=None, decoration=None, elevator=None,
                  community=None):
    """统一预测入口：先 Spark 后统计降级，任何异常都走统计估算。"""
    params = {
        "district": district,
        "square": square,
        "room_num": room_num,
        "hall_num": hall_num,
        "total_floors": total_floors,
        "decoration": decoration,
        "elevator": elevator,
        "community": community,
    }
    try:
        result = _call_spark(params)
        if result is not None:
            return result
    except Exception:
        pass

    try:
        return _call_statistic(district, square, decoration, elevator,
                               total_floors, community)
    except Exception:
        # 兜底：彻底无法估算时返回 0，仍保证结构完整
        return {"predicted_total_price": 0.0, "predicted_unit_price": 0.0,
                "engine": "statistic", "community_matched": False}
