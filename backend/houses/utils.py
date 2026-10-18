"""
公共工具模块：统一 JSON 响应结构与参数解析辅助。

统一约定：
    成功 -> {"code": 0, "msg": "success", "data": <数据>}
    失败 -> {"code": <非0>, "msg": "<错误信息>"}

三个业务 app（users / houses / analysis）共用本模块。
"""
import json
from decimal import Decimal

from django.http import JsonResponse


class _DecimalEncoder(json.JSONEncoder):
    """JSON 编码器：将 Decimal 统一序列化为 float。"""

    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def ok(data=None, msg="success"):
    """成功响应：code 固定为 0。"""
    return JsonResponse(
        {"code": 0, "msg": msg, "data": data},
        encoder=_DecimalEncoder,
        json_dumps_params={"ensure_ascii": False},
    )


def fail(msg, code=1, http_status=400):
    """失败响应：code 非 0，可指定 HTTP 状态码（如 401/405/500）。"""
    return JsonResponse(
        {"code": code, "msg": msg},
        status=http_status,
        json_dumps_params={"ensure_ascii": False},
    )


def get_json(request):
    """解析请求体 JSON（容错），非 JSON 或解析失败时返回空字典。"""
    try:
        if request.content_type and "application/json" in request.content_type:
            raw = request.body.decode("utf-8") or "{}"
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def get_params(request):
    """
    合并取参：查询参数(GET) + 表单参数(POST) + JSON 请求体。

    前端 common.js 以 application/json 提交，故此处同时兼容表单与 JSON。
    """
    params = {}
    params.update(request.GET.dict())
    if request.method != "GET":
        params.update(request.POST.dict())
        params.update(get_json(request))
    return params


def to_float(value, default=None):
    """安全转 float，失败返回默认值。"""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value, default=None):
    """安全转 int（兼容 "3" / "3.0"），失败返回默认值。"""
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def num(value):
    """数值输出辅助：None 原样返回，其余尝试转 float（覆盖 Decimal）。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def pearson(xs, ys):
    """皮尔逊相关系数（纯 Python 实现，避免为图表引入 numpy 依赖）。"""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sxx = syy = 0.0
    for x, y in zip(xs, ys):
        dx = x - mx
        dy = y - my
        sxy += dx * dy
        sxx += dx * dx
        syy += dy * dy
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / ((sxx ** 0.5) * (syy ** 0.5))


def linear_fit(xs, ys):
    """最小二乘一元线性拟合，返回 (斜率, 截距)。"""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sxy = 0.0
    for x, y in zip(xs, ys):
        sxx += (x - mx) ** 2
        sxy += (x - mx) * (y - my)
    if sxx <= 0:
        return 0.0, my
    slope = sxy / sxx
    return slope, my - slope * mx
