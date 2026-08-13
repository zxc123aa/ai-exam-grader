import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    Exam,
    ExamQuestion,
    ExamQuestionStatus,
    StandardAnswer,
    StandardAnswerRevision,
    StandardAnswerRevisionStatus,
    StandardAnswerStatus,
    User,
    get_datetime_utc,
)

DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"


def _seed_question(
    session: Session,
    *,
    exam_id: uuid.UUID,
    question_key: str,
    label: str,
    question_type: str | None = None,
    knowledge_point: str | None = None,
    difficulty: int | None = None,
) -> ExamQuestion:
    question = ExamQuestion(
        exam_id=exam_id,
        question_key=question_key,
        label=label,
        question_text=f"{label} 的题干内容",
        question_type=question_type,
        knowledge_point=knowledge_point,
        difficulty=difficulty,
        status=ExamQuestionStatus.CONFIRMED,
    )
    session.add(question)
    session.flush()
    return question


def _seed_published_answer(
    session: Session,
    *,
    exam_id: uuid.UUID,
    question: ExamQuestion,
    max_score: float,
    created_by_id: uuid.UUID,
) -> StandardAnswer:
    now = get_datetime_utc()
    answer = StandardAnswer(
        exam_id=exam_id,
        exam_region_id=None,
        question_id=question.id,
        answer_text="参考答案",
        max_score=max_score,
        rubric_text="评分规则",
        scoring_points=[
            {
                "id": "p1",
                "description": "结果正确",
                "points": max_score,
                "required": True,
            }
        ],
        status=StandardAnswerStatus.READY,
        question_text=question.question_text,
        question_type=question.question_type,
    )
    session.add(answer)
    session.flush()
    revision = StandardAnswerRevision(
        standard_answer_id=answer.id,
        question_id=question.id,
        revision_number=1,
        question_key=question.question_key,
        question_text=question.question_text,
        question_type=question.question_type,
        answer_text="参考答案",
        max_score=max_score,
        rubric_text="评分规则",
        scoring_points=answer.scoring_points,
        content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status=StandardAnswerRevisionStatus.PUBLISHED,
        created_by_id=created_by_id,
        published_by_id=created_by_id,
        published_at=now,
    )
    session.add(revision)
    session.flush()
    answer.current_revision_id = revision.id
    answer.answer_hash = revision.content_hash
    answer.published_at = now
    session.add(answer)
    session.flush()
    return answer


def test_question_bank_and_compose(
    client: TestClient,
    school_owner_token_headers: dict[str, str],
    school_owner_user: tuple[User, str],
) -> None:
    exam_response = client.post(
        f"{settings.API_V1_STR}/exams/",
        headers=school_owner_token_headers,
        json={"org_id": DEFAULT_ORG_ID, "title": "题库来源卷", "subject": "物理"},
    )
    assert exam_response.status_code == 200
    exam_id = exam_response.json()["id"]

    with Session(engine) as session:
        owner = school_owner_user[0]
        source_exam = session.get(Exam, uuid.UUID(exam_id))
        assert source_exam
        q1 = _seed_question(
            session,
            exam_id=source_exam.id,
            question_key="1",
            label="第1题",
            question_type="single_choice",
            knowledge_point="电场",
            difficulty=2,
        )
        q2 = _seed_question(
            session,
            exam_id=source_exam.id,
            question_key="2",
            label="第2题",
            question_type="calculation",
            knowledge_point="光学",
            difficulty=4,
        )
        _seed_question(
            session,
            exam_id=source_exam.id,
            question_key="3",
            label="第3题",
            question_type="calculation",
        )
        answer1 = _seed_published_answer(
            session,
            exam_id=source_exam.id,
            question=q1,
            max_score=5,
            created_by_id=owner.id,
        )
        session.commit()
        q1_id, q2_id = q1.id, q2.id
        answer1_id, answer1_revision_id = answer1.id, answer1.current_revision_id

    bank_response = client.get(
        f"{settings.API_V1_STR}/exams/question-bank",
        headers=school_owner_token_headers,
    )
    assert bank_response.status_code == 200
    bank = bank_response.json()
    entries = {
        entry["question_id"]: entry
        for entry in bank["data"]
        if entry["exam_id"] == exam_id
    }
    assert len(entries) == 3
    entry1 = entries[str(q1_id)]
    assert entry1["exam_title"] == "题库来源卷"
    assert entry1["knowledge_point"] == "电场"
    assert entry1["difficulty"] == 2
    assert entry1["max_score"] == 5
    assert entry1["question_text"] == "第1题 的题干内容"
    assert entries[str(q2_id)]["max_score"] is None

    filtered = client.get(
        f"{settings.API_V1_STR}/exams/question-bank",
        headers=school_owner_token_headers,
        params={"knowledge_point": "电场"},
    ).json()
    assert [entry["question_id"] for entry in filtered["data"]] == [str(q1_id)]

    filtered = client.get(
        f"{settings.API_V1_STR}/exams/question-bank",
        headers=school_owner_token_headers,
        params={"difficulty": 4},
    ).json()
    assert [entry["question_id"] for entry in filtered["data"]] == [str(q2_id)]

    filtered = client.get(
        f"{settings.API_V1_STR}/exams/question-bank",
        headers=school_owner_token_headers,
        params={"question_type": "calculation", "knowledge_point": "光学"},
    ).json()
    assert [entry["question_id"] for entry in filtered["data"]] == [str(q2_id)]

    compose_response = client.post(
        f"{settings.API_V1_STR}/exams/compose",
        headers=school_owner_token_headers,
        json={"title": "电场光学巩固卷", "question_ids": [str(q2_id), str(q1_id)]},
    )
    assert compose_response.status_code == 200
    new_exam_id = compose_response.json()["id"]
    assert new_exam_id != exam_id

    new_questions = client.get(
        f"{settings.API_V1_STR}/exams/{new_exam_id}/questions",
        headers=school_owner_token_headers,
    ).json()["data"]
    assert [question["question_key"] for question in new_questions] == ["1", "2"]
    # 题目顺序保持 compose 请求中的选择顺序：q2 在前。
    first, second = new_questions
    assert first["label"] == "第2题"
    assert first["status"] == "confirmed"
    assert first["knowledge_point"] == "光学"
    assert first["difficulty"] == 4
    assert second["knowledge_point"] == "电场"
    assert second["region_ids"] == []

    with Session(engine) as session:
        new_answers = session.exec(
            select(StandardAnswer).where(
                StandardAnswer.exam_id == uuid.UUID(new_exam_id)
            )
        ).all()
        assert len(new_answers) == 1
        new_answer = new_answers[0]
        # 只有 q1 有已发布答案；新答案 region 留空且 revision 直接发布。
        assert str(new_answer.question_id) == second["id"]
        assert new_answer.exam_region_id is None
        assert new_answer.max_score == 5
        assert new_answer.status == StandardAnswerStatus.READY
        assert new_answer.current_revision_id is not None
        new_revision = session.get(
            StandardAnswerRevision, new_answer.current_revision_id
        )
        assert new_revision
        assert new_revision.status == StandardAnswerRevisionStatus.PUBLISHED
        assert new_revision.question_key == second["question_key"]
        assert new_revision.published_at is not None

        # 原考试不受影响。
        original_answer = session.get(StandardAnswer, answer1_id)
        assert original_answer
        assert original_answer.current_revision_id == answer1_revision_id
        original_questions = session.exec(
            select(ExamQuestion).where(ExamQuestion.exam_id == uuid.UUID(exam_id))
        ).all()
        assert len(original_questions) == 3
        assert {question.question_key for question in original_questions} == {
            "1",
            "2",
            "3",
        }

    bad_compose = client.post(
        f"{settings.API_V1_STR}/exams/compose",
        headers=school_owner_token_headers,
        json={"title": "无效组卷", "question_ids": [str(uuid.uuid4())]},
    )
    assert bad_compose.status_code == 422
