from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from app.api.routes import questions_answers
from app.core.config import settings
from app.core.db import engine
from app.models import (
    AnswerPreparationItem,
    AnswerPreparationItemStatus,
    AnswerPreparationRun,
    ExamQuestion,
    GradingItem,
    GradingRun,
    QuestionRecognitionItem,
    QuestionRecognitionRun,
    SystemConfig,
    WorkflowRunStatus,
    get_datetime_utc,
)
from app.services import grading_workflow

DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (300, 400), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_import_complete_marking_recognition_without_model_call(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    exam = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Marking handoff exam", "subject": "物理"},
    ).json()
    document_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam['id']}/files",
        headers=superuser_token_headers,
        files={"file": ("paper.png", _png(), "image/png")},
        data={"document_type": "blank_exam"},
    )
    assert document_response.status_code == 200
    document_id = document_response.json()["id"]
    page_id = f"{document_id}:page:1"
    block_id = f"{page_id}::q1"

    def fail_if_recognized(_run_id: str) -> None:
        raise AssertionError("标定结果导入不应再次调用题目识别")

    monkeypatch.setattr(
        questions_answers, "execute_question_recognition", fail_if_recognized
    )
    response = client.post(
        f"{settings.API_V1_STR}/exams/{exam['id']}/question-recognition-runs/from-marking",
        headers=superuser_token_headers,
        json={
            "document_ids": [document_id],
            "covered_page_ids": [page_id],
            "blocks": [
                {
                    "id": block_id,
                    "pageId": page_id,
                    "label": "第1题",
                    "xmin": 100,
                    "ymin": 200,
                    "xmax": 900,
                    "ymax": 500,
                }
            ],
            "results": [
                {
                    "id": block_id,
                    "blockId": block_id,
                    "sourceBlockIds": [block_id],
                    "questionNumber": "1",
                    "question": "测试题干",
                    "studentAnswer": "B",
                    "confidence": 0.94,
                }
            ],
            "layouts": [{"pageId": page_id, "rotation": 0}],
            "timing": {"totalElapsedMs": 1234},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["item_count"] == 1
    run_id = response.json()["id"]
    items = client.get(
        f"{settings.API_V1_STR}/exams/{exam['id']}/question-recognition-runs/{run_id}/items",
        headers=superuser_token_headers,
    ).json()
    assert items[0]["question_text"] == "测试题干"
    assert items[0]["student_answer_text"] == "B"
    assert items[0]["region_snapshots"][0]["exam_document_id"] == document_id

    incomplete = client.post(
        f"{settings.API_V1_STR}/exams/{exam['id']}/question-recognition-runs/from-marking",
        headers=superuser_token_headers,
        json={
            "document_ids": [document_id],
            "covered_page_ids": [f"{document_id}:page:2"],
            "blocks": [{"id": block_id, "pageId": page_id}],
            "results": [{"blockId": block_id, "question": "测试题干"}],
        },
    )
    assert incomplete.status_code == 422


def test_confirm_prepare_and_publish_immutable_revision(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    exam_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "Workflow integration exam", "subject": "物理"},
    )
    assert exam_response.status_code == 200
    exam_id = exam_response.json()["id"]
    document_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/files",
        headers=superuser_token_headers,
        files={"file": ("paper.png", _png(), "image/png")},
        data={"document_type": "blank_exam"},
    )
    assert document_response.status_code == 200
    document_id = document_response.json()["id"]

    def fake_recognition(run_id: str) -> None:
        with Session(engine) as session:
            run = session.get(QuestionRecognitionRun, run_id)
            assert run
            session.add(
                QuestionRecognitionItem(
                    run_id=run.id,
                    source_item_key="page-1-q-1",
                    question_key="1",
                    label="第1题",
                    question_text="质量为 2 kg 的物体受到 4 N 合力，求加速度。",
                    student_answer_text="2 m/s^2",
                    question_type="calculation",
                    confidence=0.93,
                    region_snapshots=[
                        {
                            "source_block_id": "page-1-q-1",
                            "exam_document_id": document_id,
                            "page_number": 1,
                            "label": "第1题",
                            "role": "primary",
                            "rotation": 270,
                            "x": 0.1,
                            "y": 0.2,
                            "width": 0.8,
                            "height": 0.2,
                        }
                    ],
                    raw_result={"provider_confidence": 0.93},
                )
            )
            run.status = WorkflowRunStatus.COMPLETED
            run.timing = {
                "orientationMs": 100,
                "layoutMs": 200,
                "cropMs": 20,
                "ocrMs": 300,
                "totalElapsedMs": 620,
            }
            run.completed_at = get_datetime_utc()
            session.add(run)
            session.commit()

    monkeypatch.setattr(
        questions_answers, "execute_question_recognition", fake_recognition
    )
    run_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/question-recognition-runs",
        headers=superuser_token_headers,
        json={"document_ids": [document_id]},
    )
    assert run_response.status_code == 200
    recognition_run_id = run_response.json()["id"]
    items_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/question-recognition-runs/{recognition_run_id}/items",
        headers=superuser_token_headers,
    )
    assert items_response.status_code == 200
    assert items_response.json()[0]["student_answer_text"] == "2 m/s^2"
    assert items_response.json()[0]["confidence"] == 0.93

    confirm_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/question-recognition-runs/{recognition_run_id}/confirm",
        headers=superuser_token_headers,
    )
    assert confirm_response.status_code == 200
    questions_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/questions",
        headers=superuser_token_headers,
    )
    assert questions_response.status_code == 200
    question = questions_response.json()["data"][0]
    assert question["status"] == "confirmed"
    assert len(question["region_ids"]) == 1

    def fake_answer_preparation(run_id: str) -> None:
        with Session(engine) as session:
            run = session.get(AnswerPreparationRun, run_id)
            assert run
            question_row = session.exec(
                select(ExamQuestion).where(ExamQuestion.exam_id == run.exam_id)
            ).one()
            session.add(
                AnswerPreparationItem(
                    run_id=run.id,
                    question_id=question_row.id,
                    source_item_key=str(question_row.id),
                    source_question_key=question_row.question_key,
                    answer_text="由 a=F/m，a=2 m/s^2。",
                    max_score=3,
                    rubric_text="公式、代入和结果各 1 分。",
                    scoring_points=[
                        {
                            "id": "p1",
                            "description": "写出 a=F/m",
                            "points": 1,
                            "required": True,
                        },
                        {
                            "id": "p2",
                            "description": "正确代入",
                            "points": 1,
                            "required": True,
                        },
                        {
                            "id": "p3",
                            "description": "结果和单位正确",
                            "points": 1,
                            "required": True,
                        },
                    ],
                    confidence=0.91,
                    match_reason="按已确认题目直接解题",
                    status=AnswerPreparationItemStatus.MATCHED,
                )
            )
            run.status = WorkflowRunStatus.COMPLETED
            run.completed_at = get_datetime_utc()
            session.add(run)
            session.commit()

    monkeypatch.setattr(
        questions_answers, "execute_answer_preparation", fake_answer_preparation
    )
    preparation_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/answer-preparation-runs",
        headers=superuser_token_headers,
        json={
            "source_type": "model",
            "provider": "pomoai",
            "model": "gpt-5.6-sol",
            "document_ids": [],
        },
    )
    assert preparation_response.status_code == 200
    preparation_run_id = preparation_response.json()["id"]
    preparation_items = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/answer-preparation-runs/{preparation_run_id}/items",
        headers=superuser_token_headers,
    ).json()
    assert preparation_items[0]["status"] == "matched"

    answer_confirm_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/answer-preparation-runs/{preparation_run_id}/confirm",
        headers=superuser_token_headers,
    )
    assert answer_confirm_response.status_code == 200
    revisions_response = client.get(
        f"{settings.API_V1_STR}/exams/{exam_id}/standard-answers/revisions",
        headers=superuser_token_headers,
    )
    revisions = revisions_response.json()["data"]
    assert len(revisions) == 1
    assert revisions[0]["status"] == "draft"
    assert revisions[0]["source_provider"] == "pomoai"
    assert revisions[0]["source_model"] == "gpt-5.6-sol"

    publish_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/standard-answers/publish",
        headers=superuser_token_headers,
        json={"revision_ids": [revisions[0]["id"]]},
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["data"][0]["status"] == "published"
    published_revision_id = publish_response.json()["data"][0]["id"]

    immutable_response = client.patch(
        f"{settings.API_V1_STR}/exams/{exam_id}/answer-preparation-items/{preparation_items[0]['id']}",
        headers=superuser_token_headers,
        json={"answer_text": "不允许覆盖历史答案"},
    )
    assert immutable_response.status_code == 409

    submission_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam_id}/submissions",
        headers=superuser_token_headers,
        files={"file": ("student.png", _png(), "image/png")},
        data={"student_name": "测试学生", "student_identifier": "T001"},
    )
    assert submission_response.status_code == 200
    submission_id = submission_response.json()["id"]
    grading_response = client.post(
        f"{settings.API_V1_STR}/grading/runs",
        headers=superuser_token_headers,
        json={
            "exam_id": exam_id,
            "submission_ids": [submission_id],
            "provider": "pomoai",
            "model": "gpt-5.6-sol",
        },
    )
    assert grading_response.status_code == 200
    grading_run_id = grading_response.json()["id"]
    locked = grading_response.json()["config_snapshot"]["answer_revision_ids"]
    assert locked[question["id"]] == published_revision_id

    def fail_without_external_model(payload):
        return grading_workflow.WorkResult(
            payload=payload, error="synthetic test failure"
        )

    monkeypatch.setattr(grading_workflow, "_process_item", fail_without_external_model)
    start_response = client.post(
        f"{settings.API_V1_STR}/grading/runs/{grading_run_id}/start",
        headers=superuser_token_headers,
    )
    assert start_response.status_code == 200
    with Session(engine) as session:
        grading_run = session.get(GradingRun, grading_run_id)
        assert grading_run
        assert grading_run.error_message is None, grading_run.error_message
        grading_item = session.exec(
            select(GradingItem).where(GradingItem.grading_run_id == grading_run.id)
        ).one()
        assert str(grading_item.question_id) == question["id"]
        assert str(grading_item.answer_revision_id) == published_revision_id


def _clear_system_config(db: Session) -> None:
    for row in db.exec(select(SystemConfig)).all():
        db.delete(row)
    db.commit()


def test_question_recognition_run_uses_system_config(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    """创建识别 run 的 provider/model 来自系统设置 recognition_*，缺键回落 vision 默认。"""
    _clear_system_config(db)
    monkeypatch.setattr(
        questions_answers, "execute_question_recognition", lambda _run_id: None
    )
    exam = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=superuser_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "识别配置考试", "subject": "物理"},
    ).json()
    document_response = client.post(
        f"{settings.API_V1_STR}/exams/{exam['id']}/files",
        headers=superuser_token_headers,
        files={"file": ("paper.png", _png(), "image/png")},
        data={"document_type": "blank_exam"},
    )
    assert document_response.status_code == 200
    document_id = document_response.json()["id"]

    try:
        # 缺键回落：recognition_* → vision 默认
        fallback_response = client.post(
            f"{settings.API_V1_STR}/exams/{exam['id']}/question-recognition-runs",
            headers=superuser_token_headers,
            json={"document_ids": [document_id]},
        )
        assert fallback_response.status_code == 200
        assert fallback_response.json()["provider"] == settings.VISION_DEFAULT_PROVIDER
        assert fallback_response.json()["model"] == settings.VISION_DEFAULT_MODEL

        patch_response = client.patch(
            f"{settings.API_V1_STR}/platform/system-config",
            headers=superuser_token_headers,
            json={
                "recognition_provider": "pomoai",
                "recognition_model": "gpt-5.5",
            },
        )
        assert patch_response.status_code == 200, patch_response.text

        run_response = client.post(
            f"{settings.API_V1_STR}/exams/{exam['id']}/question-recognition-runs",
            headers=superuser_token_headers,
            json={"document_ids": [document_id]},
        )
        assert run_response.status_code == 200
        assert run_response.json()["provider"] == "pomoai"
        assert run_response.json()["model"] == "gpt-5.5"
    finally:
        _clear_system_config(db)
