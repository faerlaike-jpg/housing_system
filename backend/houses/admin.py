"""房源模块后台管理配置。"""
from django.contrib import admin

from .models import HouseInfo, HouseValuation, PredictHistory, UserFavorite


@admin.register(HouseInfo)
class HouseInfoAdmin(admin.ModelAdmin):
    """房源明细后台：展示关键字段，支持过滤与搜索。"""

    list_display = ("id", "title", "district", "community", "total_price", "unit_price", "square")
    list_filter = ("district", "decoration", "elevator")
    search_fields = ("title", "community")
    ordering = ("id",)


@admin.register(PredictHistory)
class PredictHistoryAdmin(admin.ModelAdmin):
    """预测历史后台。"""

    list_display = ("predict_id", "user", "district", "square", "predicted_total_price",
                    "predicted_unit_price", "created_at")
    list_filter = ("district", "decoration")
    search_fields = ("district",)


@admin.register(UserFavorite)
class UserFavoriteAdmin(admin.ModelAdmin):
    """房源收藏后台。"""

    list_display = ("fav_id", "user", "house_id", "created_at")
    search_fields = ("user__username",)
    ordering = ("-created_at",)


@admin.register(HouseValuation)
class HouseValuationAdmin(admin.ModelAdmin):
    """房源性价比估值后台（由 batch_valuation.py 批量写入，这里只读查看）。"""

    list_display = ("house_id", "actual_total_price", "predicted_total_price",
                    "peer_unit_price", "peer_deviation_pct", "updated_at")
    ordering = ("peer_deviation_pct",)
    search_fields = ("house_id",)
