import os
from celery import Celery

# -----------------------
# Redis Broker & Backend
# -----------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# -----------------------
# Celery App
# -----------------------
celery_app = Celery(
    "bus_tracker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks.analytics", "app.tasks.current_stop"]
)

# -----------------------
# Config
# -----------------------
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    broker_transport_options={"visibility_timeout": 3600},  # 1 hour
    result_expires=3600,  # expire results in 1 hour
    worker_concurrency=4,  # adjust based on CPU cores
    task_acks_late=True,  # retry if worker crashes
    worker_prefetch_multiplier=1  # prevent task hogging
)

# -----------------------
# Debug startup
# -----------------------
if __name__ == "__main__":
    celery_app.start()
