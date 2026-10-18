"""
users 应用初始迁移。

说明：SysUser 对应表 sys_user 由 sql/schema.sql 创建（managed = False），
本迁移不会生成任何建表 SQL，其作用是提供一个迁移节点，
以满足 django.contrib.admin 对 AUTH_USER_MODEL 的 swappable 依赖
（admin.0001_initial -> users.__first__），否则执行 migrate 会抛出
NodeNotFoundError。
"""
from django.contrib.auth.models import UserManager
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="SysUser",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("is_superuser", models.BooleanField(
                    default=False, verbose_name="superuser status")),
                ("username", models.CharField(max_length=150, unique=True, verbose_name="username")),
                ("first_name", models.CharField(blank=True, max_length=150, verbose_name="first name")),
                ("last_name", models.CharField(blank=True, max_length=150, verbose_name="last name")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="email address")),
                ("is_staff", models.BooleanField(default=False, verbose_name="staff status")),
                ("is_active", models.BooleanField(default=True, verbose_name="active")),
                ("date_joined", models.DateTimeField(verbose_name="date joined")),
                ("phone", models.CharField(blank=True, default="", max_length=20, verbose_name="手机号")),
                ("avatar", models.CharField(default="default_avatar.png", max_length=255, verbose_name="头像")),
                ("role", models.SmallIntegerField(default=0, verbose_name="角色")),
                ("groups", models.ManyToManyField(
                    blank=True, related_name="user_set", related_query_name="user",
                    to="auth.group", verbose_name="groups")),
                ("user_permissions", models.ManyToManyField(
                    blank=True, related_name="user_set", related_query_name="user",
                    to="auth.permission", verbose_name="user permissions")),
            ],
            options={
                "verbose_name": "系统用户",
                "verbose_name_plural": "系统用户",
                "db_table": "sys_user",
                "managed": False,
            },
            managers=[
                ("objects", UserManager()),
            ],
        ),
    ]
