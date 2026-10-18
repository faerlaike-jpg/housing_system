"""房源模块视图：列表 / 对比 / 地图数据 / 预测 / 导出（FBV + 统一 JSON 响应）。"""
from django.core.paginator import Paginator
from django.db.models import F, FloatField
from django.db.models.functions import Abs
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from analysis.models import StatDistrict
from houses.utils import ok, fail, get_params, to_float, to_int, num, linear_fit

from .exporter import export_houses
from .models import CommunityEncoding, HouseInfo, HouseValuation, PredictHistory, UserFavorite
from .predict import predict_price

# 潍坊市各区县近似经纬度（用于地图打点），未匹配到则使用默认坐标
DISTRICT_COORDS = {
    "奎文区": (119.137, 36.707),
    "潍城区": (119.024, 36.728),
    "坊子区": (119.166, 36.654),
    "寒亭区": (119.218, 36.775),
    "临朐县": (118.543, 36.512),
    "昌乐县": (118.830, 36.707),
    "青州市": (118.479, 36.685),
    "诸城市": (119.410, 35.995),
    "寿光市": (118.791, 36.857),
    "安丘市": (119.219, 36.478),
    "高密市": (119.757, 36.383),
    "昌邑市": (119.398, 36.858),
    # 数据集内出现的功能区
    "高新技术产业开发区": (119.170, 36.720),
    "经济技术开发区": (119.100, 36.760),
}
DEFAULT_COORD = (119.16, 36.70)

# 性价比分档：以「相对同区域同户型均价的偏离度」为准（阈值取自 1.8 万条实际分布的分位数）
#   之所以不直接用模型残差做主标签：随机森林会向均值回归，
#   会把低价房源系统性地判成"低于市价"，用同类比价更稳健。
VALUATION_TIERS = (
    (-20.0, "明显低于市场价", "success"),
    (-8.0, "略低于市场价", "cyan"),
    (8.0, "接近市场价", "grey"),
    (20.0, "略高于市场价", "warning"),
    (None, "明显高于市场价", "danger"),
)

# 详情页「同区域价位定位」散点图的抽样上限：
# 一个区的房源可能有几千条，全部返回既慢又糊，等距抽样后趋势更清晰
POSITION_SAMPLE_LIMIT = 500


def _valuation_level(pct):
    """按偏离度百分比返回 (中文标签, 前端 status-tag 变体)。"""
    if pct is None:
        return None, None
    for threshold, label, tag in VALUATION_TIERS:
        if threshold is None or pct < threshold:
            return label, tag
    return None, None


def _attach_valuation(items):
    """给房源字典列表批量附加性价比估值，一次查询避免 N+1。"""
    if not items:
        return items
    ids = [it.get("id") for it in items if it.get("id") is not None]
    if not ids:
        return items
    try:
        valuations = {v.house_id: v for v in HouseValuation.objects.filter(house_id__in=ids)}
    except Exception:
        # 估值表不存在或查询异常时不影响主流程
        return items

    for it in items:
        v = valuations.get(it.get("id"))
        if v is None:
            it["valuation"] = None
            continue
        peer_pct = float(v.peer_deviation_pct) if v.peer_deviation_pct is not None else None
        label, tag = _valuation_level(peer_pct)
        it["valuation"] = {
            "predicted_total_price": num(v.predicted_total_price),
            "predicted_unit_price": num(v.predicted_unit_price),
            "actual_total_price": num(v.actual_total_price),
            "deviation_pct": float(v.deviation_pct) if v.deviation_pct is not None else None,
            "peer_unit_price": num(v.peer_unit_price),
            "peer_deviation_pct": peer_pct,
            "level_label": label,
            "level_tag": tag,
        }
    return items


def _house_dict(house):
    """房源对象转字典，字段与 model 一致，Decimal 转 float。"""
    return {
        "id": house.id,
        "title": house.title,
        "total_price": num(house.total_price),
        "unit_price": house.unit_price,
        "square": num(house.square),
        "size": house.size,
        "room_num": house.room_num,
        "hall_num": house.hall_num,
        "floor": house.floor,
        "floor_type": house.floor_type,
        "total_floors": house.total_floors,
        "direction": house.direction,
        "type": house.type,
        "district": house.district,
        "nearby": house.nearby,
        "community": house.community,
        "decoration": house.decoration,
        "elevator": house.elevator,
        "elevator_num": house.elevator_num,
        "ownership": house.ownership,
    }


def _build_queryset(params):
    """按查询参数构建房源 QuerySet（支持各条件组合，id 升序）。"""
    qs = HouseInfo.objects.all()

    district = (params.get("district") or "").strip()
    if district:
        qs = qs.filter(district__icontains=district)

    min_price = to_float(params.get("min_price"))
    if min_price is not None:
        qs = qs.filter(total_price__gte=min_price)
    max_price = to_float(params.get("max_price"))
    if max_price is not None:
        qs = qs.filter(total_price__lte=max_price)

    min_square = to_float(params.get("min_square"))
    if min_square is not None:
        qs = qs.filter(square__gte=min_square)
    max_square = to_float(params.get("max_square"))
    if max_square is not None:
        qs = qs.filter(square__lte=max_square)

    room_num = to_int(params.get("room_num"))
    if room_num is not None:
        qs = qs.filter(room_num=room_num)

    decoration = (params.get("decoration") or "").strip()
    if decoration:
        qs = qs.filter(decoration__icontains=decoration)

    elevator = (params.get("elevator") or "").strip()
    if elevator:
        qs = qs.filter(elevator__icontains=elevator)

    return qs.order_by("id")


@require_GET
def house_list(request):
    """GET 房源列表：多条件过滤 + 分页。"""
    try:
        params = get_params(request)
        qs = _build_queryset(params)

        page = to_int(params.get("page"), 1) or 1
        page_size = to_int(params.get("page_size"), 10) or 10
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)

        paginator = Paginator(qs, page_size)
        page_obj = paginator.get_page(page)

        data = {
            "total": paginator.count,
            "page": page_obj.number,
            "page_size": page_size,
            "total_pages": paginator.num_pages,
            "list": _attach_valuation([_house_dict(h) for h in page_obj.object_list]),
        }
        return ok(data)
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


def _extreme_id(houses, attr, want_max):
    """在非空值中取某字段的极值对应的房源 id，无有效值返回 None。"""
    pairs = [(h.id, float(getattr(h, attr))) for h in houses if getattr(h, attr) is not None]
    if not pairs:
        return None
    chooser = max if want_max else min
    return chooser(pairs, key=lambda item: item[1])[0]


@require_GET
def house_compare(request):
    """GET 房源对比：ids 逗号分隔，限定 2-4 个。"""
    try:
        ids_raw = request.GET.get("ids", "")
        ids = [x.strip() for x in ids_raw.split(",") if x.strip()]
        if not 2 <= len(ids) <= 4:
            return fail("请选择 2-4 个房源进行对比")

        houses = list(HouseInfo.objects.filter(id__in=ids))
        if len(houses) != len(set(ids)):
            return fail("部分房源不存在")

        best = {
            "unit_price": _extreme_id(houses, "unit_price", False),
            "total_price": _extreme_id(houses, "total_price", False),
            "square": _extreme_id(houses, "square", True),
            "room_num": _extreme_id(houses, "room_num", True),
        }
        worst = {
            "unit_price": _extreme_id(houses, "unit_price", True),
            "total_price": _extreme_id(houses, "total_price", True),
            "square": _extreme_id(houses, "square", False),
            "room_num": _extreme_id(houses, "room_num", False),
        }
        data = {
            "houses": [_house_dict(h) for h in houses],
            "best": best,
            "worst": worst,
        }
        return ok(data)
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


@require_GET
def map_data(request):
    """GET 地图打点数据：读取 stat_district 全部区域 + 经纬度 + 单价极值。"""
    try:
        items = []
        unit_prices = []
        for stat in StatDistrict.objects.all():
            lng, lat = DISTRICT_COORDS.get(stat.district, DEFAULT_COORD)
            unit_price = num(stat.avg_unit_price)
            items.append({
                "district": stat.district,
                "house_count": stat.house_count or 0,
                "avg_unit_price": unit_price,
                "avg_total_price": num(stat.avg_total_price),
                "avg_square": num(stat.avg_square),
                "lng": lng,
                "lat": lat,
            })
            if unit_price is not None:
                unit_prices.append(unit_price)

        data = {
            "list": items,
            "min_unit_price": min(unit_prices) if unit_prices else 0,
            "max_unit_price": max(unit_prices) if unit_prices else 0,
        }
        return ok(data)
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


def _recommend_houses(district, square):
    """同区域按 |面积差| 升序取 4 条；不足则放宽到全表。"""
    def _query(base_qs):
        return list(
            base_qs.exclude(square=None)
            .annotate(diff=Abs(F("square") - square, output_field=FloatField()))
            .order_by("diff")[:4]
        )

    recommends = _query(HouseInfo.objects.filter(district=district)) if district else []
    if len(recommends) < 4:
        recommends = _query(HouseInfo.objects.all())
    return [_house_dict(h) for h in recommends]


@require_POST
def house_predict(request):
    """POST 房价预测 + 相似房源推荐；登录用户写入预测历史。

    权限：预测与预测历史绑定，仅登录用户可用（游客不可预测）。
    """
    try:
        user = request.user
        if not user or not user.is_authenticated:
            return fail("请先登录后再使用房价预测", code=401, http_status=401)

        params = get_params(request)
        district = (params.get("district") or "").strip()
        square = to_float(params.get("square"))
        room_num = to_int(params.get("room_num"))
        hall_num = to_int(params.get("hall_num"))
        total_floors = to_int(params.get("total_floors"))
        decoration = params.get("decoration")
        elevator = params.get("elevator")
        # 升级模型新增：小区名称（用于查小区目标编码，可留空）
        community = (params.get("community") or "").strip() or None

        if not district:
            return fail("请选择所属区域")
        if square is None or square <= 0:
            return fail("请填写有效的房屋面积")

        result = predict_price(
            district=district, square=square, room_num=room_num, hall_num=hall_num,
            total_floors=total_floors, decoration=decoration, elevator=elevator,
            community=community,
        )
        predicted_total_price = result["predicted_total_price"]
        predicted_unit_price = result["predicted_unit_price"]

        # 已登录则记录预测历史（失败不影响主流程）
        if request.user.is_authenticated:
            try:
                PredictHistory.objects.create(
                    user=request.user,
                    district=district,
                    square=square,
                    room_num=room_num,
                    hall_num=hall_num,
                    total_floors=total_floors,
                    decoration=decoration,
                    elevator=elevator,
                    predicted_total_price=predicted_total_price,
                    predicted_unit_price=predicted_unit_price,
                    created_at=timezone.now(),
                )
            except Exception:
                pass

        data = {
            "predicted_total_price": predicted_total_price,
            "predicted_unit_price": predicted_unit_price,
            "engine": result.get("engine"),
            # 是否命中了小区编码（前端据此提示"已按小区均价校准"）
            "community_matched": bool(result.get("community_matched")),
            "community": community,
            "recommend_houses": _attach_valuation(_recommend_houses(district, square)),
        }
        return ok(data)
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


@require_GET
def community_list(request):
    """
    小区列表（供预测表单的自动补全使用）。

    只返回挂牌量最多的前 N 个小区，避免一次返回 1750 条拖慢页面。
    支持 ?district= 过滤，?q= 模糊搜索，?limit= 限制条数。
    """
    try:
        limit = to_int(request.GET.get("limit")) or 500
        limit = max(1, min(limit, 1750))
        district = (request.GET.get("district") or "").strip()
        keyword = (request.GET.get("q") or "").strip()

        qs = CommunityEncoding.objects.all()
        if district:
            qs = qs.filter(district=district)
        if keyword:
            qs = qs.filter(community__icontains=keyword)

        rows = list(
            qs.order_by("-house_count").values(
                "community", "district", "house_count", "te_value"
            )[:limit]
        )
        data = [{
            "community": r["community"],
            "district": r["district"],
            "house_count": r["house_count"],
            "te_value": num(r["te_value"]),
        } for r in rows]
        return ok({"total": len(data), "list": data})
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


@require_GET
def house_position(request):
    """
    GET 某房源在「同区域 面积-总价 分布」中的位置（详情页价位定位图使用）。

    返回同区域抽样散点、最小二乘拟合线与该房源自身坐标，
    用于直观回答「这套房在同区域里偏贵还是偏便宜」。
    """
    try:
        house_id = to_int(request.GET.get("id"))
        if house_id is None:
            return fail("缺少房源编号")
        house = HouseInfo.objects.filter(id=house_id).first()
        if house is None:
            return fail("房源不存在或已下架")

        empty = {"district": house.district, "total": 0, "sample_size": 0,
                 "points": [], "fit": None, "house": None}
        if house.square is None or house.total_price is None or not house.district:
            return ok(empty)

        rows = list(
            HouseInfo.objects
            .filter(district=house.district, square__isnull=False, total_price__isnull=False)
            .order_by("id")
            .values_list("square", "total_price")
        )
        total = len(rows)
        if total == 0:
            return ok(empty)

        step = max(1, total // POSITION_SAMPLE_LIMIT)
        sample = rows[::step][:POSITION_SAMPLE_LIMIT]
        xs = [float(s) for s, _ in sample]
        ys = [float(p) for _, p in sample]
        slope, intercept = linear_fit(xs, ys)

        return ok({
            "district": house.district,
            "total": total,
            "sample_size": len(sample),
            "points": [
                {"square": round(float(s), 2), "total_price": round(float(p), 2)}
                for s, p in sample
            ],
            "fit": {"slope": round(slope, 6), "intercept": round(intercept, 4)},
            "house": {
                "id": house.id,
                "square": float(house.square),
                "total_price": float(house.total_price),
                "unit_price": num(house.unit_price),
            },
        })
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


@require_GET
def export_view(request):
    """GET 导出台账：参数与 list 一致，另加 file_type=csv|xlsx。

    权限：导出属于"数据索取"类操作，仅普通用户及以上可用（游客不可导出）。
    """
    try:
        user = request.user
        if not user or not user.is_authenticated:
            return fail("请先登录后再导出数据", code=401, http_status=401)

        params = get_params(request)
        file_type = (params.get("file_type") or "csv").lower()
        if file_type not in ("csv", "xlsx"):
            file_type = "csv"

        qs = _build_queryset(params)
        rows = [_house_dict(h) for h in qs]
        return export_houses(rows, file_type)
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


def _is_favorited(user, house_id):
    """当前登录用户是否已收藏该房源；未登录一律返回 False。"""
    if not user or not user.is_authenticated:
        return False
    try:
        return UserFavorite.objects.filter(user_id=user.id, house_id=house_id).exists()
    except Exception:
        return False


@require_GET
def house_detail(request):
    """GET 单套房源详情（附带当前用户是否已收藏）。"""
    try:
        house_id = to_int(request.GET.get("id"))
        if house_id is None:
            return fail("缺少房源编号")
        house = HouseInfo.objects.filter(id=house_id).first()
        if house is None:
            return fail("房源不存在或已下架")
        data = _house_dict(house)
        data["favorited"] = _is_favorited(request.user, house_id)
        _attach_valuation([data])
        return ok(data)
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


@require_POST
def favorite_toggle(request):
    """POST 收藏 / 取消收藏（切换语义），需登录。"""
    try:
        user = request.user
        if not user or not user.is_authenticated:
            return fail("请先登录后再收藏房源", code=401, http_status=401)
        params = get_params(request)
        house_id = to_int(params.get("house_id"))
        if house_id is None:
            return fail("缺少房源编号")
        if not HouseInfo.objects.filter(id=house_id).exists():
            return fail("房源不存在或已下架")

        existing = UserFavorite.objects.filter(user_id=user.id, house_id=house_id).first()
        if existing is not None:
            existing.delete()
            return ok({"favorited": False})
        UserFavorite.objects.create(user_id=user.id, house_id=house_id,
                                    created_at=timezone.now())
        return ok({"favorited": True})
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


@require_GET
def favorite_list(request):
    """GET 当前用户的收藏房源列表（按收藏时间倒序）。"""
    try:
        user = request.user
        if not user or not user.is_authenticated:
            return fail("请先登录", code=401, http_status=401)

        limit = to_int(request.GET.get("limit"), 100) or 100
        limit = min(max(limit, 1), 500)
        favs = list(UserFavorite.objects.filter(user_id=user.id)[:limit])

        house_ids = [f.house_id for f in favs]
        houses = {h.id: h for h in HouseInfo.objects.filter(id__in=house_ids)}

        items = []
        for fav in favs:
            house = houses.get(fav.house_id)
            if house is None:
                continue  # 房源已不存在（如被 ETL 重写掉）则跳过
            item = _house_dict(house)
            item["favorited"] = True
            item["favorited_at"] = (fav.created_at.strftime("%Y-%m-%d %H:%M")
                                    if fav.created_at else None)
            items.append(item)
        return ok({"list": items, "total": len(items)})
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


@require_GET
def favorite_ids(request):
    """GET 当前用户已收藏的房源 id 列表（供列表页标记收藏状态）。"""
    try:
        user = request.user
        if not user or not user.is_authenticated:
            return ok({"logged_in": False, "ids": []})
        ids = list(UserFavorite.objects.filter(user_id=user.id)
                   .values_list("house_id", flat=True))
        return ok({"logged_in": True, "ids": ids})
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


@require_GET
def predict_history(request):
    """GET 当前用户的房价预测历史记录（个人中心展示）。"""
    try:
        user = request.user
        if not user or not user.is_authenticated:
            return fail("请先登录", code=401, http_status=401)

        limit = to_int(request.GET.get("limit"), 30) or 30
        limit = min(max(limit, 1), 200)
        records = PredictHistory.objects.filter(user_id=user.id)[:limit]

        items = [{
            "predict_id": r.predict_id,
            "district": r.district,
            "square": num(r.square),
            "room_num": r.room_num,
            "hall_num": r.hall_num,
            "total_floors": r.total_floors,
            "decoration": r.decoration,
            "elevator": r.elevator,
            "predicted_total_price": num(r.predicted_total_price),
            "predicted_unit_price": num(r.predicted_unit_price),
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else None,
        } for r in records]
        return ok({"list": items, "total": len(items)})
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


@require_POST
def predict_history_delete(request):
    """POST 删除当前用户的一条预测记录（只能删自己的记录）。"""
    try:
        user = request.user
        if not user or not user.is_authenticated:
            return fail("请先登录", code=401, http_status=401)

        params = get_params(request)
        predict_id = to_int(params.get("predict_id"))
        if predict_id is None:
            return fail("缺少记录编号")

        # 带 user_id 过滤，避免越权删除他人记录
        deleted, _ = PredictHistory.objects.filter(
            predict_id=predict_id, user_id=user.id).delete()
        if not deleted:
            return fail("记录不存在或无权删除")
        return ok({"predict_id": predict_id})
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)
