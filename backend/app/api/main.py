from fastapi import APIRouter

from app.api.routes import (
    classes,
    exams,
    files,
    grading,
    login,
    orgs,
    platform,
    private,
    questions_answers,
    students,
    tasks,
    users,
    utils,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(exams.router)
api_router.include_router(classes.router)
api_router.include_router(students.router)
api_router.include_router(questions_answers.router)
api_router.include_router(files.router)
api_router.include_router(tasks.router)
api_router.include_router(grading.router)
api_router.include_router(platform.router)
api_router.include_router(orgs.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
