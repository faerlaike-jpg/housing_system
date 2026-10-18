"""房源模块路由（根路由已 include 到 /api/house/）。"""
from django.urls import path

from . import views

app_name = "houses"

urlpatterns = [
    path("list/", views.house_list, name="list"),
    path("detail/", views.house_detail, name="detail"),
    path("position/", views.house_position, name="position"),
    path("compare/", views.house_compare, name="compare"),
    path("map_data/", views.map_data, name="map_data"),
    path("predict/", views.house_predict, name="predict"),
    path("community_list/", views.community_list, name="community_list"),
    path("predict_history/", views.predict_history, name="predict_history"),
    path("predict_history/delete/", views.predict_history_delete, name="predict_history_delete"),
    path("favorite/", views.favorite_toggle, name="favorite"),
    path("favorites/", views.favorite_list, name="favorites"),
    path("favorite_ids/", views.favorite_ids, name="favorite_ids"),
    path("export/", views.export_view, name="export"),
]
