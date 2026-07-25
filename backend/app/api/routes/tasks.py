import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SessionDep, is_superuser
from app.models import (
    ProcessingTask,
    ProcessingTaskCreate,
    ProcessingTaskPublic,
    ProcessingTaskStatus,
)
from app.worker import process_test_task, run_test_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/test", response_model=ProcessingTaskPublic)
def create_test_task(
    *, session: SessionDep, current_user: CurrentUser, task_in: ProcessingTaskCreate
) -> Any:
    task = ProcessingTask(
        task_type=task_in.task_type,
        status=ProcessingTaskStatus.QUEUED,
        progress=0,
        created_by_id=current_user.id,
        input_ref={"source": "api"},
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    try:
        process_test_task.send(str(task.id))
    except Exception:
        run_test_task(str(task.id))
        session.refresh(task)
    return task


@router.get("/{task_id}", response_model=ProcessingTaskPublic)
def read_task(
    session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID
) -> Any:
    task = session.get(ProcessingTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not is_superuser(current_user) and task.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return task
