from typing import Any

from fastapi import APIRouter, Depends, UploadFile

from app.api.deps import CurrentUser, SessionDep, get_current_teacher_user
from app.models import StoredFilePublic
from app.services import billing as billing_service
from app.services.file_storage import store_upload_file

router = APIRouter(
    prefix="/files",
    tags=["files"],
    dependencies=[Depends(get_current_teacher_user)],
)


@router.post("/upload", response_model=StoredFilePublic)
async def upload_file(
    *, session: SessionDep, current_user: CurrentUser, file: UploadFile
) -> Any:
    if current_user.org_id:
        billing_service.require_model_entitlement(session, current_user.org_id)
    return await store_upload_file(
        session=session, current_user=current_user, file=file
    )
