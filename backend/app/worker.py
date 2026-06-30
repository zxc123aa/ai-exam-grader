import dramatiq
from dramatiq.brokers.redis import RedisBroker
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.models import ProcessingTask, ProcessingTaskStatus, get_datetime_utc

redis_broker = RedisBroker(url=settings.REDIS_URL)
dramatiq.set_broker(redis_broker)


@dramatiq.actor
def process_test_task(task_id: str) -> None:
    run_test_task(task_id)


def run_test_task(task_id: str) -> None:
    with Session(engine) as session:
        task = session.get(ProcessingTask, task_id)
        if not task:
            return
        task.status = ProcessingTaskStatus.RUNNING
        task.progress = 50
        task.updated_at = get_datetime_utc()
        session.add(task)
        session.commit()

        task.status = ProcessingTaskStatus.SUCCEEDED
        task.progress = 100
        task.output_ref = {"message": "Test task completed"}
        task.updated_at = get_datetime_utc()
        session.add(task)
        session.commit()
