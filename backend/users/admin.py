"""用户模块后台管理配置。

注意：SysUser 为 managed=False 且未创建 Django 权限体系的 M2M 关联表
（sys_user_groups / sys_user_user_permissions），因此这里使用普通 ModelAdmin，
并通过 fields 明确限定表单字段，避免渲染 groups / user_permissions 导致查询报错。
用户密码统一由登录 / 注册 API 维护。
"""
from django.contrib import admin

from .models import SysUser


@admin.register(SysUser)
class SysUserAdmin(admin.ModelAdmin):
    """系统用户后台：查看与维护注册用户信息。"""

    list_display = ("id", "username", "email", "phone", "role", "is_staff", "is_active", "date_joined")
    list_filter = ("role", "is_staff", "is_active")
    search_fields = ("username", "email", "phone")
    ordering = ("-date_joined",)

    # 仅暴露标量字段，排除 groups / user_permissions 两个 M2M
    fields = ("username", "email", "phone", "avatar", "role",
              "first_name", "last_name", "is_staff", "is_active",
              "last_login", "date_joined")
    readonly_fields = ("last_login", "date_joined")
