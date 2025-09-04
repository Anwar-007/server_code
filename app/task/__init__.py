from app.tasks.analytics import run_analytics_task

# 👇 Add all task imports here so Celery auto-discovers them
__all__ = [
    "run_analytics_task",
]
