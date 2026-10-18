"""
潍坊市二手房房价预测系统 - Django 全局配置
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ============================ 基础安全配置 ============================
SECRET_KEY = "django-insecure-housing-system-weifang-2024-graduation-project"
DEBUG = True
ALLOWED_HOSTS = ["*"]

# ============================ 应用注册 ============================
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 业务应用
    "users",
    "houses",
    "analysis",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "housing_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "housing_project.wsgi.application"
ASGI_APPLICATION = "housing_project.asgi.application"

# ============================ 数据库配置 ============================
# 业务表由 sql/schema.sql 创建，Django 模型均为 managed=False，只做读写不做建表。
# 支持环境变量覆盖，便于同一份代码在「本机开发」与「虚拟机部署」之间切换：
#   DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("DB_NAME", "housing_db"),
        "USER": os.environ.get("DB_USER", "root"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "000000"),
        "HOST": os.environ.get("DB_HOST", "192.168.100.102"),
        "PORT": os.environ.get("DB_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
    }
}

# ============================ 自定义用户模型 ============================
AUTH_USER_MODEL = "users.SysUser"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 6}},
]

# ============================ 国际化 ============================
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = False  # 与 MySQL DATETIME / NOW() 保持一致

# ============================ 静态与模板资源 ============================
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ============================ 登录跳转 ============================
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

# ============================ 机器学习模型路径 ============================
# 训练脚本 train_rf_model.py 保存的随机森林模型目录（本地路径，便于直接加载）
RF_MODEL_PATH = os.environ.get(
    "RF_MODEL_PATH",
    str(BASE_DIR.parent / "spark_jobs" / "models" / "rf_housing_model"),
)
