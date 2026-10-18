import os
import sys
import threading

from django.apps import AppConfig


class HousesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "houses"
    verbose_name = "房源模块"

    def ready(self):
        """
        后台线程预热 Spark 预测服务，避免第一个预测请求等待十几秒的冷启动。

        runserver 自动重载会起两个进程，只有实际干活的那个（RUN_MAIN=true）需要预热；
        用 --noreload 时只有一个进程（如 systemd 托管），它自己就要预热。
        """
        args = sys.argv
        is_reload_parent = (
            "runserver" in args
            and "--noreload" not in args
            and os.environ.get("RUN_MAIN") != "true"
        )
        if is_reload_parent:
            return
        try:
            from .predict import warm_up
        except Exception:
            return
        threading.Thread(target=warm_up, daemon=True).start()
