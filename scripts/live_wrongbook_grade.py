"""Local live check: reference answers -> submission -> grading -> release -> wrongbook.

Continues the exam created by live_wrongbook_verify.py. Talks only to localhost and
never prints tokens or passwords.
"""

from __future__ import annotations

import json
import secrets
import sys
import time

from live_wrongbook_verify import ROOT, _must, _request, login
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import WrongQuestionEntry, WrongQuestionSource
from app.services.object_storage import materialize_storage_key

EXAM_ID = "d4989b5c-5d16-49c6-94c9-0e47c2c305be"
ORG_ID = "5b60ddfe-5353-47d1-b20e-65f16b09297c"
MATERIAL = ROOT / "参考算法" / "2_试卷分析文件" / "material"
ANSWER_SHEETS = [MATERIAL / "1.jpg", MATERIAL / "2.jpg"]
DONE = {"completed", "completed_with_errors", "failed"}


def wait_for(path: str, token: str, *, label: str, timeout: int) -> dict:
    """Poll a run endpoint until it stops moving, printing each status change."""
    deadline = time.time() + timeout
    seen: str | None = None
    while time.time() < deadline:
        status, payload = _request("GET", path, token=token)
        data = _must(status, payload)
        assert isinstance(data, dict)
        state = str(data.get("status"))
        if state != seen:
            print(f"  {label} -> {state}", flush=True)
            seen = state
        if state in DONE:
            return data
        time.sleep(5)
    raise RuntimeError(f"timeout waiting for {label}, last status={seen}")


def published_answer_count(token: str) -> int:
    status, revisions = _request(
        "GET", f"/exams/{EXAM_ID}/standard-answers/revisions", token=token
    )
    data = _must(status, revisions)
    assert isinstance(data, dict)
    return sum(
        1 for row in data.get("data") or [] if row.get("status") == "published"
    )


def prepare_answers(token: str) -> None:
    already = published_answer_count(token)
    if already:
        print(f"ANSWERS_ALREADY_PUBLISHED {already}, skipping preparation")
        return
    status, run = _request(
        "POST",
        f"/exams/{EXAM_ID}/answer-preparation-runs",
        token=token,
        json_body={"source_type": "model", "document_ids": []},
    )
    run_data = _must(status, run)
    assert isinstance(run_data, dict)
    run_id = run_data["id"]
    print(f"ANSWER_RUN {run_id} model={run_data.get('model')}")
    final = wait_for(
        f"/exams/{EXAM_ID}/answer-preparation-runs/{run_id}",
        token,
        label="answer_preparation",
        timeout=900,
    )
    if final.get("status") == "failed":
        raise RuntimeError(f"answer preparation failed: {final.get('error_message')}")

    status, items = _request(
        "GET",
        f"/exams/{EXAM_ID}/answer-preparation-runs/{run_id}/items",
        token=token,
    )
    item_rows = _must(status, items)
    assert isinstance(item_rows, list)
    for item in item_rows:
        points = item.get("scoring_points") or []
        print(
            f"ANSWER {item.get('source_question_key')} status={item.get('status')} "
            f"answer_len={len(str(item.get('answer_text') or ''))} points={len(points)}"
        )
        # Confirm rejects any linked item that is not matched, so lift conflicts.
        if item.get("question_id") and item.get("status") != "matched":
            status, patched = _request(
                "PATCH",
                f"/exams/{EXAM_ID}/answer-preparation-items/{item['id']}",
                token=token,
                json_body={"status": "matched"},
            )
            _must(status, patched)
            print(f"  -> forced matched ({item.get('status')})")

    status, confirmed = _request(
        "POST",
        f"/exams/{EXAM_ID}/answer-preparation-runs/{run_id}/confirm",
        token=token,
    )
    _must(status, confirmed)
    status, published = _request(
        "POST",
        f"/exams/{EXAM_ID}/standard-answers/publish",
        token=token,
        json_body={"revision_ids": []},
    )
    published_data = _must(status, published)
    assert isinstance(published_data, dict)
    print(f"PUBLISHED_ANSWERS {published_data.get('count')}")


def find_student(token: str) -> tuple[str, str]:
    status, classes = _request("GET", "/classes/", token=token)
    class_rows = _must(status, classes)
    assert isinstance(class_rows, dict)
    for row in class_rows.get("data") or []:
        status, students = _request(
            "GET", f"/classes/{row['id']}/students", token=token
        )
        student_rows = _must(status, students)
        assert isinstance(student_rows, dict)
        for student in student_rows.get("data") or []:
            print(f"STUDENT {student.get('name')} class={row.get('name')}")
            return str(row["name"]), str(student["name"])
    raise RuntimeError("no student found in this org")


def upload_submission(token: str, class_name: str, student_name: str) -> str:
    status, existing = _request("GET", f"/exams/{EXAM_ID}/submissions", token=token)
    existing_data = _must(status, existing)
    assert isinstance(existing_data, dict)
    for row in existing_data.get("data") or []:
        print(
            f"SUBMISSION_REUSED {row['id']} pages={row.get('page_count')} "
            f"bound_student={bool(row.get('student_id'))}"
        )
        return str(row["id"])

    first, *rest = ANSWER_SHEETS
    status, submission = _request(
        "POST",
        f"/exams/{EXAM_ID}/submissions",
        token=token,
        files=[("file", first.name, first.read_bytes(), "image/jpeg")],
        data_fields={
            "student_name": student_name,
            "class_name": class_name,
            "preprocess": "auto",
        },
    )
    data = _must(status, submission)
    assert isinstance(data, dict)
    submission_id = data["id"]
    print(
        f"SUBMISSION {submission_id} bound_student={bool(data.get('student_id'))} "
        f"registration={data.get('registration_status')}"
    )
    for page in rest:
        status, appended = _request(
            "POST",
            f"/exams/{EXAM_ID}/submissions/{submission_id}/pages",
            token=token,
            files=[("file", page.name, page.read_bytes(), "image/jpeg")],
            data_fields={"preprocess": "auto"},
        )
        appended_data = _must(status, appended)
        assert isinstance(appended_data, dict)
        print(f"  appended {page.name} pages={appended_data.get('page_count')}")
    return str(submission_id)


def grade(token: str, submission_id: str) -> str:
    status, run = _request(
        "POST",
        "/grading/runs",
        token=token,
        # recognition_run_id only accepts a grading-side recognition_preview run;
        # our questions came from the question-recognition workflow, so omit it.
        json_body={"exam_id": EXAM_ID, "submission_ids": [submission_id]},
    )
    run_data = _must(status, run)
    assert isinstance(run_data, dict)
    run_id = run_data["id"]
    print(f"GRADING_RUN {run_id} status={run_data.get('status')}")
    status, started = _request("POST", f"/grading/runs/{run_id}/start", token=token)
    _must(status, started)
    final = wait_for(f"/grading/runs/{run_id}", token, label="grading", timeout=1800)
    print(
        f"GRADING {final.get('status')} graded={final.get('graded_count')} "
        f"error={final.get('error_message')}"
    )
    return str(run_id)


def clear_review_queue(token: str, run_id: str) -> int:
    status, queue = _request(
        "GET", f"/grading/runs/{run_id}/review-queue", token=token
    )
    rows = _must(status, queue)
    assert isinstance(rows, list)
    cleared = 0
    for row in rows:
        annotation_id = row.get("annotation_id")
        if not annotation_id:
            continue
        score = row.get("score")
        print(
            f"REVIEW {row.get('label')} risk={row.get('risk')} "
            f"score={score}/{row.get('max_score')} confidence={row.get('confidence')}"
        )
        status, patched = _request(
            "PATCH",
            f"/exams/{EXAM_ID}/submissions/{row['submission_id']}"
            f"/annotations/{annotation_id}",
            token=token,
            json_body={
                "score": float(score or 0),
                "audit_reason": "本地验证：确认建议评分",
            },
        )
        _must(status, patched)
        cleared += 1
    print(f"REVIEW_CLEARED {cleared}/{len(rows)}")
    return cleared


def inspect_wrongbook() -> dict:
    summary = {"sources": 0, "entries": 0, "wrong": 0, "crops": 0, "missing_crops": 0}
    with Session(engine) as session:
        sources = session.exec(
            select(WrongQuestionSource).where(WrongQuestionSource.exam_id == EXAM_ID)
        ).all()
        summary["sources"] = len(sources)
        source_ids = [item.id for item in sources]
        for source in sources:
            print(
                f"SOURCE {source.question_label} max={source.max_score} "
                f"knowledge={source.knowledge_point_names} "
                f"answer_len={len(source.standard_answer_text or '')} "
                f"points={len(source.scoring_points)}"
            )
        if not source_ids:
            return summary
        entries = session.exec(
            select(WrongQuestionEntry).where(
                WrongQuestionEntry.source_id.in_(source_ids)
            )
        ).all()
        summary["entries"] = len(entries)
        for entry in entries:
            crop_note = "no-crop"
            if entry.image_storage_key:
                summary["crops"] += 1
                try:
                    path = materialize_storage_key(entry.image_storage_key)
                    crop_note = (
                        f"{path.suffix} {path.stat().st_size // 1024}KB"
                        if path.exists()
                        else "MISSING_FILE"
                    )
                    if not path.exists():
                        summary["missing_crops"] += 1
                except Exception as exc:  # noqa: BLE001 - report, do not abort
                    crop_note = f"ERROR {exc}"
                    summary["missing_crops"] += 1
            if entry.is_wrong:
                summary["wrong"] += 1
            print(
                f"ENTRY {entry.question_label} score={entry.score}/{entry.max_score} "
                f"wrong={entry.is_wrong} learner={bool(entry.learner_id)} "
                f"student_user={bool(entry.student_user_id)} "
                f"missed={len(entry.missed_points)} crop={crop_note}"
            )
    return summary


def main() -> int:
    missing = [str(path) for path in ANSWER_SHEETS if not path.exists()]
    if missing:
        raise SystemExit(f"missing answer sheets: {missing}")

    admin = login(settings.FIRST_SUPERUSER, settings.FIRST_SUPERUSER_PASSWORD)
    owner_email = f"wb-owner-grade-{secrets.token_hex(3)}@example.com"
    owner_password = secrets.token_urlsafe(12)
    status, owner = _request(
        "POST",
        f"/platform/orgs/{ORG_ID}/owners",
        token=admin,
        json_body={
            "email": owner_email,
            "full_name": "错题本验证老师",
            "password": owner_password,
        },
    )
    _must(status, owner)
    token = login(owner_email, owner_password)

    prepare_answers(token)
    class_name, student_name = find_student(token)
    submission_id = upload_submission(token, class_name, student_name)
    run_id = grade(token, submission_id)
    clear_review_queue(token, run_id)

    status, release = _request(
        "POST",
        f"/grading/exams/{EXAM_ID}/score-releases",
        token=token,
        json_body={"reason": "本地验证发布"},
    )
    release_data = _must(status, release)
    assert isinstance(release_data, dict)
    print(f"RELEASE v{release_data.get('version')} at {release_data.get('created_at')}")

    summary = inspect_wrongbook()
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["entries"] and not summary["missing_crops"] else 4


if __name__ == "__main__":
    sys.exit(main())
