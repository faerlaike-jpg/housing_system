# -*- coding: utf-8 -*-
"""角色权限控制：管理员判定的唯一入口。

设计原则（答辩要点）：
    「前端藏按钮」只是体验优化，真正的拦截必须在后端做一遍。
    所有管理类接口统一挂 @admin_required / 页面统一用 AdminRequiredMixin，
    越权请求返回 403——用 curl 直接调接口同样拿不到数据。

角色定义（sys_user.role）：
    0 普通用户：浏览 + 预测 + 收藏 + 导出
    1 管理员：普通用户全部能力 + 数据/用户/模型运维
"""

from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from houses.utils import fail


def is_admin(user):
    """管理员判定：role=1 / 超级用户 / 可登录后台（Django Admin 需要 is_staff）。

    真正的判定逻辑放在 SysUser.is_admin 上，这里只做「未登录」兜底，
    避免两处实现漂移。
    """
    if not user or not user.is_authenticated:
        return False
    return bool(getattr(user, "is_admin", False))


def admin_required(view_func):
    """API 装饰器：未登录返回 401，已登录但非管理员返回 403。"""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user or not user.is_authenticated:
            return fail("请先登录", code=401, http_status=401)
        if not is_admin(user):
            return fail("无权限访问：该功能仅管理员可用", code=403, http_status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """管理员专属页面：未登录跳登录页，已登录但非管理员返回 403。"""

    login_url = "/login/"

    def test_func(self):
        return is_admin(self.request.user)
