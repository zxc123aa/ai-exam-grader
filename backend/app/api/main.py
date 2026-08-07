from fastapi import APIRouter

from app.api.routes import (
    classes,
    commerce,
    exams,
    files,
    grading,
    login,
    model_offerings,
    orgs,
    platform,
    private,
    provider_channels,
    questions_answers,
    students,
    users,
    utils,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(commerce.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(exams.router)
api_router.include_router(classes.router)
api_router.include_router(students.router)
api_router.include_router(questions_answers.router)
api_router.include_router(files.router)
api_router.include_router(grading.router)
api_router.include_router(platform.router)
api_router.include_router(provider_channels.router)
api_router.include_router(model_offerings.router)
api_router.include_router(orgs.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
    from app.api.routes import tasks

    api_router.include_router(tasks.router)
