# celery_app.py
from celery import Celery
import os

REDIS_DSN = os.getenv("REDIS_DSN", "redis://redis:6379/0")

celery_app = Celery(
    "bus_tasks",
    broker=REDIS_DSN,
    backend=REDIS_DSN
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
