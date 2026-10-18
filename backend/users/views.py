"""用户模块视图：注册 / 登录 / 登出 / 个人信息（FBV + 统一 JSON 响应）。"""
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.utils import timezone

from houses.utils import ok, fail, get_params
from .models import SysUser


def _user_dict(user):
    """将用户对象转为前端所需字典。"""
    return {
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "phone": getattr(user, "phone", "") or "",
        "avatar": getattr(user, "avatar", "") or "",
        "role": user.role,
        "date_joined": user.date_joined.strftime("%Y-%m-%d %H:%M:%S") if user.date_joined else None,
    }


def register(request):
    """POST 注册：入参 username / password / email / phone。"""
    if request.method != "POST":
        return fail("请求方法不允许", http_status=405)
    try:
        params = get_params(request)
        username = (params.get("username") or "").strip()
        password = params.get("password") or ""
        email = (params.get("email") or "").strip()
        phone = (params.get("phone") or "").strip()

        if len(username) < 3:
            return fail("用户名长度不能少于 3 位")
        if len(password) < 6:
            return fail("密码长度不能少于 6 位")
        if SysUser.objects.filter(username=username).exists():
            return fail("用户名已存在")

        # managed=False 不影响 create_user 的 ORM 写入
        user = SysUser.objects.create_user(
            username=username, password=password, email=email, phone=phone,
        )
        return ok({"user_id": user.id, "username": user.username})
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


def login_view(request):
    """POST 登录：入参 username / password，成功后建立会话。"""
    if request.method != "POST":
        return fail("请求方法不允许", http_status=405)
    try:
        params = get_params(request)
        username = (params.get("username") or "").strip()
        password = params.get("password") or ""
        if not username or not password:
            return fail("请输入用户名和密码")

        user = authenticate(request, username=username, password=password)
        if user is None:
            return fail("用户名或密码错误")

        login(request, user)
        # 显式刷新最后登录时间（login 已通过信号更新，此处兜底确保写入）
        SysUser.objects.filter(pk=user.pk).update(last_login=timezone.now())
        return ok({"user_id": user.id, "username": user.username, "role": user.role})
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


def logout_view(request):
    """登出：清除会话，返回空数据。"""
    try:
        logout(request)
        return ok(None)
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)


def profile(request):
    """GET 查询当前登录用户信息；POST 修改资料 / 密码。"""
    try:
        user = request.user
        if not user or not user.is_authenticated:
            return fail("未登录或登录已过期", code=401, http_status=401)

        if request.method == "GET":
            return ok(_user_dict(user))

        if request.method == "POST":
            params = get_params(request)

            # ---- 修改密码（需校验旧密码）----
            new_password = params.get("new_password")
            if new_password:
                old_password = params.get("old_password")
                if not old_password or not user.check_password(old_password):
                    return fail("原密码不正确")
                if len(new_password) < 6:
                    return fail("新密码长度不能少于 6 位")
                user.set_password(new_password)

            # ---- 修改基本资料（仅更新传入字段）----
            if "email" in params:
                user.email = (params.get("email") or "").strip()
            if "phone" in params:
                user.phone = (params.get("phone") or "").strip()
            if "avatar" in params:
                user.avatar = (params.get("avatar") or "").strip()
            if "first_name" in params:
                user.first_name = params.get("first_name") or ""
            if "last_name" in params:
                user.last_name = params.get("last_name") or ""

            # managed=False 下 save() 会对已有行执行 UPDATE，正常
            user.save()
            if new_password:
                # 密码变更后刷新会话，避免当前用户被登出
                update_session_auth_hash(request, user)
            return ok(_user_dict(user))

        return fail("请求方法不允许", http_status=405)
    except Exception as e:
        return fail(f"服务异常：{e}", http_status=500)
