"""
根路由：页面路由（渲染模板） + 业务 API 路由（RESTful）
"""
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from analysis.views import OpsPageView

urlpatterns = [
    # ---------------- Django 后台（用户管理 / 数据管理） ----------------
    path("admin/", admin.site.urls),

    # ---------------- 页面路由（服务端渲染模板） ----------------
    path("", TemplateView.as_view(template_name="data_list.html"), name="index"),
    path("login/", TemplateView.as_view(template_name="login.html"), name="login_page"),
    path("data-list/", TemplateView.as_view(template_name="data_list.html"), name="data_list_page"),
    path("dashboard/", TemplateView.as_view(template_name="visual_dashboard.html"), name="dashboard_page"),
    path("compare/", TemplateView.as_view(template_name="house_compare.html"), name="compare_page"),
    path("heat-map/", TemplateView.as_view(template_name="heat_map.html"), name="heat_map_page"),
    path("predict/", TemplateView.as_view(template_name="predict_form.html"), name="predict_page"),
    path("house/<int:house_id>/", TemplateView.as_view(template_name="house_detail.html"),
         name="house_detail_page"),
    path("profile/", TemplateView.as_view(template_name="profile.html"), name="profile_page"),
    # 管理员专属：大数据与模型运维面板（未登录跳登录页；普通用户 403）
    path("ops/", OpsPageView.as_view(), name="ops_page"),

    # ---------------- 业务 API ----------------
    path("api/user/", include("users.urls")),
    path("api/house/", include("houses.urls")),
    path("api/analysis/", include("analysis.urls")),
]
