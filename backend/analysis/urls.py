"""统计分析模块路由（根路由已 include 到 /api/analysis/）。"""
from django.urls import path

from . import views

app_name = "analysis"

urlpatterns = [
    path("stats/", views.stats, name="stats"),
    path("relations/", views.relations, name="relations"),
    # 管理员专属：大数据与模型运维面板数据
    path("ops_status/", views.ops_status, name="ops_status"),
]
