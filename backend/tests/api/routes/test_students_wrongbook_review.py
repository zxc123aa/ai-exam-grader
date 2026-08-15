import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Organization,
    UserRole,
    WrongQuestionEntry,
    WrongQuestionErrorReason,
    WrongQuestionReview,
    WrongQuestionReviewResult,
)
from app.services.wrongbook_review import next_interval_days
from tests.api.routes.test_students_wrongbook import (
    _bind_student_account,
    _graded_exam,
    _headers,
    _publish,
    _user,
)
from tests.utils.utils import random_lower_string


def _student_context(client: TestClient, db: Session, name: str) -> dict:
    org = Organization(name=f"复习学校-{name}", code=f"review-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner, owner_password = _user(db, UserRole.SCHOOL_OWNER, org)
    owner_headers = _headers(client, owner, owner_password)
    exam, student, _submission = _graded_exam(
        db, org, owner, student_name=name, second_question="full"
    )
    student_user, student_password = _bind_student_account(db, org, student)
    _publish(client, exam, owner_headers)
    return {
        "exam": exam,
        "student_user": student_user,
        "headers": _headers(client, student_user, student_password),
    }


def test_review_advances_schedule_and_leaves_due_queue(
    client: TestClient, db: Session
) -> None:
    context = _student_context(client, db, "复习甲")
    headers = context["headers"]

    due = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/due", headers=headers
    )
    assert due.status_code == 200, due.text
    # 满分题不进复习队列，只有错题进
    assert due.json()["count"] == 1
    entry_id = due.json()["data"][0]["entry_id"]
    assert due.json()["data"][0]["review_count"] == 0

    first = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry_id}/review",
        headers=headers,
        json={"result": "good"},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["review_count"] == 1
    assert body["interval_days"] == 1
    assert body["due_count"] == 0

    # 复习过就离开今天的队列
    assert (
        client.get(
            f"{settings.API_V1_STR}/students/me/wrongbook/due", headers=headers
        ).json()["count"]
        == 0
    )
    # 列表里能看到复习次数与下次到期
    listed = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=headers
    ).json()["data"][0]
    assert listed["review_count"] == 1
    assert listed["next_due_at"] is not None

    # 到期后重新出现，答对继续往后推
    review = db.exec(
        select(WrongQuestionReview).where(
            WrongQuestionReview.entry_id == uuid.UUID(entry_id)
        )
    ).one()
    review.next_due_at = datetime.now(UTC) - timedelta(minutes=1)
    db.add(review)
    db.commit()
    assert (
        client.get(
            f"{settings.API_V1_STR}/students/me/wrongbook/due", headers=headers
        ).json()["count"]
        == 1
    )
    second = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry_id}/review",
        headers=headers,
        json={"result": "good"},
    )
    assert second.json()["review_count"] == 2
    assert second.json()["interval_days"] == 3

    # 答错回到第一档，但复习次数继续累加
    review = db.exec(
        select(WrongQuestionReview).where(
            WrongQuestionReview.entry_id == uuid.UUID(entry_id)
        )
    ).one()
    review.next_due_at = datetime.now(UTC) - timedelta(minutes=1)
    db.add(review)
    db.commit()
    again = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry_id}/review",
        headers=headers,
        json={"result": "again"},
    )
    assert again.json()["interval_days"] == 1
    assert again.json()["review_count"] == 3


def test_interval_progression_is_bounded() -> None:
    """连续答对逐档前进并停在最长间隔；hard 原地，again 归零。"""
    intervals = []
    index = -1
    for _ in range(6):
        days = next_interval_days(index, WrongQuestionReviewResult.GOOD)
        intervals.append(days)
        index = [1, 3, 7, 15, 30].index(days)
    assert intervals == [1, 3, 7, 15, 30, 30]
    assert next_interval_days(2, WrongQuestionReviewResult.HARD) == 7
    assert next_interval_days(2, WrongQuestionReviewResult.AGAIN) == 1
    assert next_interval_days(0, WrongQuestionReviewResult.EASY) == 7


def test_mastery_counts_full_marks_as_attempts(client: TestClient, db: Session) -> None:
    """掌握度的分母是「做过几道」，所以满分题也要算进 attempts。"""
    context = _student_context(client, db, "复习乙")
    headers = context["headers"]

    mastery = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/mastery", headers=headers
    )
    assert mastery.status_code == 200, mastery.text
    rows = mastery.json()["data"]
    # 只有第 1 题挂了知识点，第 2 题（满分）没挂
    assert len(rows) == 1
    row = rows[0]
    assert row["knowledge_point_name"] == "功和功率"
    assert row["attempts"] == 1
    assert row["wrong_count"] == 1
    assert row["wrong_rate"] == 100
    assert row["last_wrong_at"] is not None
    assert row["last_reviewed_at"] is None

    entry_id = str(
        db.exec(
            select(WrongQuestionEntry.id).where(
                WrongQuestionEntry.student_user_id == context["student_user"].id,
                WrongQuestionEntry.is_wrong.is_(True),  # type: ignore[union-attr]
            )
        ).one()
    )
    client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry_id}/review",
        headers=headers,
        json={"result": "good"},
    )
    after = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/mastery", headers=headers
    ).json()["data"][0]
    assert after["last_reviewed_at"] is not None


def test_cram_list_prefers_never_reviewed_and_bigger_losses(
    client: TestClient, db: Session
) -> None:
    context = _student_context(client, db, "复习丙")
    headers = context["headers"]

    cram = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/cram", headers=headers
    )
    assert cram.status_code == 200, cram.text
    assert [item["question_label"] for item in cram.json()["data"]] == ["第1题"]

    # 按学科筛选：不存在的学科返回空
    empty = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/cram?subject=化学",
        headers=headers,
    )
    assert empty.json()["count"] == 0


def test_review_endpoints_reject_other_students_and_teachers(
    client: TestClient, db: Session
) -> None:
    context = _student_context(client, db, "复习丁")
    entry_id = str(
        db.exec(
            select(WrongQuestionEntry.id).where(
                WrongQuestionEntry.student_user_id == context["student_user"].id,
                WrongQuestionEntry.is_wrong.is_(True),  # type: ignore[union-attr]
            )
        ).one()
    )

    other = _student_context(client, db, "复习戊")
    forbidden = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry_id}/review",
        headers=other["headers"],
        json={"result": "good"},
    )
    assert forbidden.status_code == 404

    org = db.get(Organization, context["exam"].org_id)
    assert org is not None
    teacher, password = _user(db, UserRole.TEACHER, org)
    teacher_headers = _headers(client, teacher, password)
    for path in ("due", "mastery", "cram"):
        assert (
            client.get(
                f"{settings.API_V1_STR}/students/me/wrongbook/{path}",
                headers=teacher_headers,
            ).status_code
            == 403
        )


def _wrong_entry_id(client: TestClient, headers: dict[str, str]) -> str:
    due = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/due", headers=headers
    )
    assert due.status_code == 200, due.text
    return due.json()["data"][0]["entry_id"]


def test_review_and_patch_record_error_reason(client: TestClient, db: Session) -> None:
    context = _student_context(client, db, "错因甲")
    headers = context["headers"]
    entry_id = _wrong_entry_id(client, headers)

    # 复习提交时顺手标注错因，直接落到条目上
    reviewed = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry_id}/review",
        headers=headers,
        json={"result": "good", "error_reason": "calculation"},
    )
    assert reviewed.status_code == 200, reviewed.text
    db.expire_all()
    entry = db.get(WrongQuestionEntry, uuid.UUID(entry_id))
    assert entry is not None
    assert entry.error_reason == WrongQuestionErrorReason.CALCULATION

    # 列表与详情都带错因
    detail = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry_id}",
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["error_reason"] == "calculation"
    listed = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=headers
    ).json()["data"][0]
    assert listed["error_reason"] == "calculation"

    # PATCH 单独改错因；传 null 清除
    patched = client.patch(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry_id}",
        headers=headers,
        json={"error_reason": "concept"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["error_reason"] == "concept"
    db.expire_all()
    entry = db.get(WrongQuestionEntry, uuid.UUID(entry_id))
    assert entry is not None
    assert entry.error_reason == WrongQuestionErrorReason.CONCEPT

    cleared = client.patch(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry_id}",
        headers=headers,
        json={"error_reason": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["error_reason"] is None


def test_error_reason_rejects_invalid_values_and_other_students(
    client: TestClient, db: Session
) -> None:
    context = _student_context(client, db, "错因乙")
    headers = context["headers"]
    entry_id = _wrong_entry_id(client, headers)

    bad_review = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry_id}/review",
        headers=headers,
        json={"result": "good", "error_reason": "careless"},
    )
    assert bad_review.status_code == 422
    bad_patch = client.patch(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry_id}",
        headers=headers,
        json={"error_reason": "粗心"},
    )
    assert bad_patch.status_code == 422

    # 别人的错题与不存在的错题返回同一个结果
    other = _student_context(client, db, "错因丙")
    forbidden = client.patch(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry_id}",
        headers=other["headers"],
        json={"error_reason": "concept"},
    )
    assert forbidden.status_code == 404
