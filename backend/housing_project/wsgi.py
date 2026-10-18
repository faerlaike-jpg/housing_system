"""WSGI 部署入口。"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "housing_project.settings")

application = get_wsgi_application()
