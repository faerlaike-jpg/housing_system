from django.contrib.auth.models import AbstractUser
from django.db import models


class SysUser(AbstractUser):
    """
    系统用户模型，映射到 MySQL 表 sys_user。

    字段与 Django AbstractUser 对齐（username/password/email/is_staff/...），
    额外扩展 phone、avatar、role 三个业务字段。
    表由 sql/schema.sql 创建，因此 managed = False。
    """

    phone = models.CharField("手机号", max_length=20, blank=True, default="")
    avatar = models.CharField("头像", max_length=255, default="default_avatar.png")
    role = models.SmallIntegerField("角色", default=0)  # 0 普通用户 / 1 管理员

    class Meta:
        managed = False
        db_table = "sys_user"
        verbose_name = "系统用户"
        verbose_name_plural = "系统用户"

    def __str__(self):
        return self.username

    @property
    def is_admin(self):
        """管理员判定：role=1 / 超级用户 / 可登录后台（Django Admin 需要 is_staff）。

        这是全项目唯一的角色判定口径，前端模板（菜单显隐）与后端装饰器
        （users.permissions.admin_required）都复用它，避免两处规则不一致。
        """
        return self.role == 1 or self.is_superuser or self.is_staff
