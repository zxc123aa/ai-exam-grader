"""Local live check for knowledge tagging + wrongbook snapshot.

Talks only to localhost. Does not print tokens or passwords.
"""

from __future__ import annotations

import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import ExamQuestion, ExamQuestionKnowledgeLink

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000/api/v1"
PAPERS = [
    ROOT / "参考算法" / "2_试卷分析文件" / "material" / "1.jpg",
    ROOT / "参考算法" / "2_试卷分析文件" / "material" / "2.jpg",
]
STATE_PATH = ROOT / "scripts" / ".live_wrongbook_verify_state.json"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    json_body: dict | None = None,
    form: dict[str, str] | None = None,
    files: list[tuple[str, str, bytes, str]] | None = None,
    data_fields: dict[str, str] | None = None,
) -> tuple[int, object]:
    url = path if path.startswith("http") else f"{API}{path}"
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body: bytes | None = None
    if json_body is not None:
        payload = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
        body = payload
    elif form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif files is not None:
        boundary = "----LiveVerify" + secrets.token_hex(8)
        chunks: list[bytes] = []
        for key, value in (data_fields or {}).items():
            chunks.append(f"--{boundary}\r\n".encode())
            chunks.append(
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
            )
        for field, filename, content, content_type in files:
            chunks.append(f"--{boundary}\r\n".encode())
            chunks.append(
                (
                    f'Content-Disposition: form-data; name="{field}"; '
                    f'filename="{filename}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode()
            )
            chunks.append(content)
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        body = b"".join(chunks)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=120) as resp:
            raw = resp.read()
            if not raw:
                return resp.status, {}
            try:
                return resp.status, json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return resp.status, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, parsed


def _must(status: int, payload: object, expected: int = 200) -> object:
    if status != expected:
        raise RuntimeError(f"HTTP {status}: {payload}")
    return payload


def login(email: str, password: str) -> str:
    status, payload = _request(
        "POST",
        "/login/access-token",
        form={"username": email, "password": password},
    )
    data = _must(status, payload)
    assert isinstance(data, dict)
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("login did not return access_token")
    return token


def poll(method: str, path: str, token: str, ok, *, timeout: int, label: str) -> object:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status, payload = _request(method, path, token=token)
        last = (status, payload)
        if status == 200 and ok(payload):
            print(f"OK {label}")
            return payload
        time.sleep(4)
    raise RuntimeError(f"timeout waiting for {label}: {last}")


def print_knowledge_links(exam_id: str) -> int:
    linked = 0
    with Session(engine) as session:
        questions = session.exec(
            select(ExamQuestion)
            .where(ExamQuestion.exam_id == exam_id)
            .order_by(ExamQuestion.created_at.desc())
        ).all()
        print(f"CONFIRMED_QUESTIONS {len(questions)}")
        for question in questions:
            n = len(
                session.exec(
                    select(ExamQuestionKnowledgeLink).where(
                        ExamQuestionKnowledgeLink.question_id == question.id
                    )
                ).all()
            )
            if n:
                linked += 1
            print(
                f"{question.label} | {question.knowledge_point} | links={n}"
            )
    return linked


def main() -> int:
    missing = [str(path) for path in PAPERS if not path.exists()]
    if missing:
        raise SystemExit(f"missing papers: {missing}")

    suffix = secrets.token_hex(3)
    owner_email = f"wb-owner-{suffix}@example.com"
    owner_password = secrets.token_urlsafe(12)
    student_no = f"WB{suffix[:6].upper()}"
    class_name = f"错题本验证{suffix[:4]}"

    admin = login(settings.FIRST_SUPERUSER, settings.FIRST_SUPERUSER_PASSWORD)
    status, org = _request(
        "POST",
        "/platform/orgs",
        token=admin,
        json_body={
            "name": f"错题本实测试校{suffix}",
            "code": f"wblive{suffix}",
            "owner": {
                "email": owner_email,
                "full_name": "错题本验证老师",
                "password": owner_password,
            },
        },
    )
    org_data = _must(status, org)
    assert isinstance(org_data, dict)
    org_id = org_data["id"]
    print(f"ORG {org_data['code']} {org_id}")

    token = login(owner_email, owner_password)
    status, class_payload = _request(
        "POST",
        "/classes/",
        token=token,
        json_body={"name": class_name, "grade_level": "八年级"},
    )
    class_data = _must(status, class_payload)
    assert isinstance(class_data, dict)
    class_id = class_data["id"]
    status, batch = _request(
        "POST",
        f"/classes/{class_id}/students/batch",
        token=token,
        json_body={
            "create_accounts": True,
            "rows": [{"name": "验证学生", "student_no": student_no}],
        },
    )
    _must(status, batch)
    student_email = f"{student_no}@school.local"
    print(f"STUDENT_LOGIN {student_email}")

    status, exam = _request(
        "POST",
        "/exams/",
        token=token,
        json_body={
            "title": f"错题本真实卷验证-{suffix}",
            "subject": "物理",
            "grade_level": "八年级",
            "class_ids": [class_id],
        },
    )
    exam_data = _must(status, exam)
    assert isinstance(exam_data, dict)
    exam_id = exam_data["id"]
    print(f"EXAM {exam_data['title']} subject={exam_data['subject']} {exam_id}")

    document_ids: list[str] = []
    for paper in PAPERS:
        status, doc = _request(
            "POST",
            f"/exams/{exam_id}/files",
            token=token,
            files=[("file", paper.name, paper.read_bytes(), "image/jpeg")],
            data_fields={"document_type": "blank_exam", "preprocess": "auto"},
        )
        doc_data = _must(status, doc)
        assert isinstance(doc_data, dict)
        document_ids.append(doc_data["id"])
        print(
            f"UPLOADED {paper.name} preprocess={doc_data.get('preprocessing_status')}"
        )

    def files_ready(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        rows = payload.get("data") or []
        if len(rows) < 2:
            return False
        for row in rows:
            state = row.get("preprocessing_status")
            if state in {"queued", "running"}:
                return False
        return True

    files = poll(
        "GET",
        f"/exams/{exam_id}/files",
        token,
        files_ready,
        timeout=180,
        label="preprocess",
    )
    assert isinstance(files, dict)
    for row in files.get("data") or []:
        print(
            f"FILE {row.get('original_filename')} status={row.get('preprocessing_status')}"
        )

    status, run = _request(
        "POST",
        f"/exams/{exam_id}/question-recognition-runs",
        token=token,
        json_body={"document_ids": document_ids},
    )
    run_data = _must(status, run)
    assert isinstance(run_data, dict)
    run_id = run_data["id"]
    print(f"RECOGNITION_RUN {run_id} status={run_data.get('status')}")

    def run_done(payload: object) -> bool:
        return isinstance(payload, dict) and payload.get("status") in {
            "completed",
            "completed_with_errors",
            "failed",
        }

    run_data = poll(
        "GET",
        f"/exams/{exam_id}/question-recognition-runs/{run_id}",
        token,
        run_done,
        timeout=900,
        label="recognition",
    )
    assert isinstance(run_data, dict)
    print(
        f"RECOGNITION {run_data.get('status')} items={run_data.get('item_count')} "
        f"error={run_data.get('error_message')}"
    )
    if run_data.get("status") == "failed":
        return 2

    status, items = _request(
        "GET",
        f"/exams/{exam_id}/question-recognition-runs/{run_id}/items",
        token=token,
    )
    item_rows = _must(status, items)
    assert isinstance(item_rows, list)
    empty = 0
    for item in item_rows:
        text = str(item.get("question_text") or "").strip()
        print(
            f"ITEM {item.get('label')} status={item.get('status')} "
            f"text_len={len(text)}"
        )
        if text:
            continue
        empty += 1
        status, _excluded = _request(
            "PATCH",
            f"/exams/{exam_id}/question-recognition-items/{item['id']}",
            token=token,
            json_body={"status": "excluded"},
        )
        _must(status, _excluded)
    print(f"EXCLUDED_EMPTY {empty}/{len(item_rows)}")

    status, confirm = _request(
        "POST",
        f"/exams/{exam_id}/question-recognition-runs/{run_id}/confirm",
        token=token,
    )
    confirm_data = _must(status, confirm)
    assert isinstance(confirm_data, dict)
    print(f"CONFIRMED_AT {confirm_data.get('confirmed_at')}")
    linked = print_knowledge_links(exam_id)

    STATE_PATH.write_text(
        json.dumps(
            {
                "org_id": org_id,
                "exam_id": exam_id,
                "class_id": class_id,
                "class_name": class_name,
                "student_email": student_email,
                "student_no": student_no,
                "recognition_run_id": run_id,
                "document_ids": document_ids,
                "linked_questions": linked,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"STATE {STATE_PATH} linked_questions={linked}")
    return 0 if linked else 3


if __name__ == "__main__":
    sys.exit(main())
