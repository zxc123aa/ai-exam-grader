from typing import Any

from fastapi import APIRouter, UploadFile

from app.api.deps import CurrentUser, SessionDep
from app.models import StoredFilePublic
from app.services.file_storage import store_upload_file

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload", response_model=StoredFilePublic)
async def upload_file(
    *, session: SessionDep, current_user: CurrentUser, file: UploadFile
) -> Any:
    return await store_upload_file(
        session=session, current_user=current_user, file=file
    )
