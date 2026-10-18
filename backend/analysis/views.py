"""统计分析模块视图：离线统计结果汇总 + 实时特征关系分析（FBV + 统一 JSON 响应）。"""
from django.db import connection
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView

from houses.models import (
    CommunityEncoding,
    HouseInfo,
    HouseValuation,
    PredictHistory,
    UserFavorite,
)
from houses.utils import ok, fail, num, pearson, linear_fit
from users.models import SysUser
from users.permissions import AdminRequiredMixin, admin_required

from .models import (
    StatCommunityTop,
    StatDecoration,
    StatDistrict,
    StatFeatureImportance,
    StatModelMetric,
    StatRoomType,
)

# 参与相关性矩阵计算的数值列：(数据库字段, 中文名)
NUMERIC_FEATURES = [
    ("square", "面积"),
    ("total_price", "总价"),
    ("unit_price", "单价"),
    ("room_num", "室数"),
    ("hall_num", "厅数"),
    ("total_floors", "总楼层"),
]

# 散点图抽样上限：全量一万多条直接画会糊成一片，抽样既清晰也更快
SAMPLE_LIMIT = 800

# 随机森林特征名 -> 中文名
FEATURE_LABELS = {
    "square": "面积",
    "room_num": "室数",
    "hall_num": "厅数",
    "total_floors": "总楼层",
    "district": "所属区域",
    "decoration": "装修情况",
    "elevator": "有无电梯",
    "community_te": "小区均价（目标编码）",
}


@require_GET
def stats(request):
    """GET 统计数据：区域 / 装修 / 户型 / 热门小区 + 全局汇总。"""
    try:
        # ---- 区域统计 ----
        districts = list(StatDistrict.objects.all())
        district_stats = [
            {
                "district": d.district,
                "house_count": d.house_count or 0,
                "avg_total_price": num(d.avg_total_price),
                "avg_unit_price": num(d.avg_unit_price),
                "avg_square": num(d.avg_square),
            }
            for d in districts
        ]

        # ---- 装修统计 ----
        decoration_stats = [
            {
                "decoration": d.decoration,
                "house_count": d.house_count or 0,
                "avg_unit_price": num(d.avg_unit_price),
            }
            for d in StatDecoration.objects.all()
        ]

        # ---- 户型统计 ----
        room_stats = [
            {
                "room_num": r.room_num,
                "house_count": r.house_count or 0,
                "avg_unit_price": num(r.avg_unit_price),
            }
            for r in StatRoomType.objects.all().order_by("room_num")
        ]

        # ---- 热门小区 ----
        community_top = [
            {
                "community": c.community,
                "district": c.district,
                "house_count": c.house_count or 0,
                "avg_total_price": num(c.avg_total_price),
                "avg_unit_price": num(c.avg_unit_price),
            }
            for c in StatCommunityTop.objects.all()
        ]

        # ---- 全局汇总（按挂牌量加权平均）----
        total_houses = 0
        weighted_total = 0.0
        weighted_unit = 0.0
        for d in districts:
            count = d.house_count or 0
            total_houses += count
            if d.avg_total_price is not None:
                weighted_total += float(d.avg_total_price) * count
            if d.avg_unit_price is not None:
                weighted_unit += float(d.avg_unit_price) * count

        summary = {
            "total_houses": total_houses,
            "avg_total_price": round(weighted_total / total_houses, 2) if total_houses else 0.0,
            "avg_unit_price": round(weighted_unit / total_houses, 2) if total_houses else 0.0,
            "community_count": StatCommunityTop.objects.count(),
        }

        data = {
            "district_stats": district_stats,
            "decoration_stats": decoration_stats,
            "room_stats": room_stats,
            "community_top": community_top,
            "summary": summary,
        }
        return ok(data)
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


@require_GET
def relations(request):
    """
    GET 特征关系分析，一次返回三块内容：

    1. scatter          面积 - 总价 散点数据 + 最小二乘拟合直线 + 相关系数 r
    2. correlation      6 个数值特征两两之间的皮尔逊相关系数矩阵
    3. feature_importance  随机森林特征重要性（读取训练脚本写入的 stat_feature_importance）

    说明：散点与相关性都基于抽样后的样本（见 sample_size），
    全量数据直接画散点会糊成一片，抽样后趋势更清晰，计算也更快。
    """
    try:
        cols = [name for name, _ in NUMERIC_FEATURES]
        col_count = len(cols)

        raw_rows = list(
            HouseInfo.objects
            .filter(square__isnull=False, total_price__isnull=False)
            .order_by("id")
            .values_list(*cols, "district")
        )
        # 六列全部非空的记录才参与相关性计算，保证各列位置对齐
        rows = [r for r in raw_rows if all(r[i] is not None for i in range(col_count))]
        total = len(rows)

        if total == 0:
            return ok({
                "total_houses": 0,
                "sample_size": 0,
                "scatter": {"points": [], "fit": {"slope": 0, "intercept": 0, "r": 0}},
                "correlation": {"labels": [label for _, label in NUMERIC_FEATURES], "matrix": []},
                "feature_importance": [],
            })

        step = max(1, total // SAMPLE_LIMIT)
        sample = rows[::step][:SAMPLE_LIMIT]

        # ---- 1. 面积 - 总价 散点与拟合 ----
        squares = [float(r[0]) for r in sample]
        prices = [float(r[1]) for r in sample]
        slope, intercept = linear_fit(squares, prices)
        r_value = pearson(squares, prices)
        points = [
            {
                "square": float(r[0]),
                "total_price": float(r[1]),
                "unit_price": float(r[2]),
                "district": r[col_count],
            }
            for r in sample
        ]

        # ---- 2. 特征相关性矩阵 ----
        series = [[float(r[i]) for r in sample] for i in range(col_count)]
        matrix = [
            [round(pearson(series[i], series[j]), 4) for j in range(col_count)]
            for i in range(col_count)
        ]

        # ---- 3. 特征重要性（表由训练脚本写入，缺失时返回空数组，不影响前两块）----
        try:
            importance = [
                {
                    "feature": item.feature,
                    "label": FEATURE_LABELS.get(item.feature, item.feature),
                    "importance": num(item.importance),
                }
                for item in StatFeatureImportance.objects.all().order_by("-importance")
            ]
        except Exception:
            importance = []

        data = {
            "total_houses": total,
            "sample_size": len(sample),
            "scatter": {
                "points": points,
                "fit": {"slope": round(slope, 6),
                        "intercept": round(intercept, 4),
                        "r": round(r_value, 4)},
            },
            "correlation": {
                "labels": [label for _, label in NUMERIC_FEATURES],
                "matrix": matrix,
            },
            "feature_importance": importance,
        }
        return ok(data)
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


# =============================================================================
# 管理员专属：大数据与模型运维面板
# =============================================================================
# 面板展示的业务表清单：(表名, 中文说明, 分组, Django 模型)
OPS_TABLES = [
    ("sys_user", "用户账号", "用户与业务", SysUser),
    ("user_favorite", "房源收藏", "用户与业务", UserFavorite),
    ("predict_history", "预测历史", "用户与业务", PredictHistory),
    ("house_info", "二手房明细", "数据与统计", HouseInfo),
    ("stat_district", "区域维度统计", "数据与统计", StatDistrict),
    ("stat_decoration", "装修维度统计", "数据与统计", StatDecoration),
    ("stat_room_type", "户型维度统计", "数据与统计", StatRoomType),
    ("stat_community_top", "热门小区 TOP20", "数据与统计", StatCommunityTop),
    ("stat_feature_importance", "特征重要性", "机器学习", StatFeatureImportance),
    ("stat_model_metric", "模型评估指标", "机器学习", StatModelMetric),
    ("community_encoding", "小区目标编码", "机器学习", CommunityEncoding),
    ("house_valuation", "房源性价比估值", "机器学习", HouseValuation),
]

# 大数据链路各步骤：脚本 -> 产物。"table" 为空表示该步骤没有落库产物（常驻服务）
OPS_PIPELINE = [
    {"name": "ETL 清洗与统计", "script": "spark_etl_analytics.py",
     "output": "house_info + 4 张统计表", "table": "house_info"},
    {"name": "升级模型训练", "script": "train_upgraded_model.py",
     "output": "rf_housing_model_v2 + community_encoding", "table": "community_encoding"},
    {"name": "模型指标落库", "script": "train_upgraded_model.py",
     "output": "stat_model_metric", "table": "stat_model_metric"},
    {"name": "性价比批量打分", "script": "batch_valuation.py",
     "output": "house_valuation", "table": "house_valuation"},
    {"name": "在线预测服务", "script": "predict_service.py",
     "output": "Django 预测接口", "table": None},
]


def _table_update_times():
    """从 information_schema 读取各表的最近更新时间（InnoDB 未改动过时为 None）。"""
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT TABLE_NAME, UPDATE_TIME FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s",
                [connection.settings_dict.get("NAME")],
            )
            return {
                row[0]: (row[1].strftime("%Y-%m-%d %H:%M") if row[1] else None)
                for row in cursor.fetchall()
            }
    except Exception:
        return {}


@admin_required
@require_GET
def ops_status(request):
    """
    GET 管理员专属：大数据与模型运维面板数据。

    返回五块：
        summary     业务表数量 / 数据总行数
        tables      各业务表行数与最近更新时间
        model       线上模型评估指标（读 stat_model_metric，由训练脚本写入）
        importance  特征重要性（读 stat_feature_importance）
        pipeline    大数据链路各步骤及其产物是否就绪
    """
    try:
        update_times = _table_update_times()

        tables = []
        counts = {}
        total_rows = 0
        for name, label, group, model in OPS_TABLES:
            try:
                rows = model.objects.count()
            except Exception:
                rows = 0
            counts[name] = rows
            total_rows += rows
            tables.append({
                "name": name,
                "label": label,
                "group": group,
                "rows": rows,
                "updated_at": update_times.get(name),
            })

        # ---- 线上模型指标（表可能为空：尚未在升级脚本里跑过训练）----
        model_info = None
        try:
            metric = StatModelMetric.objects.first()
        except Exception:
            metric = None
        if metric is not None:
            model_info = {
                "algorithm": metric.algorithm,
                "feature_count": metric.feature_count,
                "num_trees": metric.num_trees,
                "max_depth": metric.max_depth,
                "rmse": num(metric.rmse),
                "mae": num(metric.mae),
                "r2": num(metric.r2),
                "mape": num(metric.mape),
                "train_rows": metric.train_rows,
                "test_rows": metric.test_rows,
                "trained_at": (metric.trained_at.strftime("%Y-%m-%d %H:%M")
                               if metric.trained_at else None),
            }

        # ---- 特征重要性 ----
        try:
            importance = [
                {
                    "feature": item.feature,
                    "label": FEATURE_LABELS.get(item.feature, item.feature),
                    "importance": num(item.importance),
                }
                for item in StatFeatureImportance.objects.all().order_by("-importance")
            ]
        except Exception:
            importance = []

        # ---- 链路步骤就绪状态：按关键表是否有数据推断 ----
        pipeline = [
            {
                "name": step["name"],
                "script": step["script"],
                "output": step["output"],
                "ready": True if step["table"] is None else counts.get(step["table"], 0) > 0,
            }
            for step in OPS_PIPELINE
        ]

        return ok({
            "summary": {"table_count": len(tables), "total_rows": total_rows},
            "tables": tables,
            "model": model_info,
            "importance": importance,
            "pipeline": pipeline,
        })
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


class OpsPageView(AdminRequiredMixin, TemplateView):
    """管理员专属页面：大数据与模型运维面板。"""

    template_name = "ops.html"
