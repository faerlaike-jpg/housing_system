"""ASGI 部署入口。"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "housing_project.settings")

application = get_asgi_application()
