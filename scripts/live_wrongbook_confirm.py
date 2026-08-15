"""Continue confirm + knowledge tagging on the last live exam."""

from __future__ import annotations

import json
import secrets
import sys
import urllib.request

# Reuse helpers from the main live script.
from live_wrongbook_verify import (
    _must,
    _request,
    login,
    print_knowledge_links,
)
from app.core.config import settings

EXAM_ID = "d4989b5c-5d16-49c6-94c9-0e47c2c305be"
ORG_ID = "5b60ddfe-5353-47d1-b20e-65f16b09297c"
RUN_ID = "66881be9-8234-40e8-a15a-4f40e15d0b92"
STUDENT_EMAIL = "WB016F5D@school.local"


def main() -> int:
    admin = login(settings.FIRST_SUPERUSER, settings.FIRST_SUPERUSER_PASSWORD)
    owner_email = f"wb-owner-cont-{secrets.token_hex(3)}@example.com"
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

    status, items = _request(
        "GET",
        f"/exams/{EXAM_ID}/question-recognition-runs/{RUN_ID}/items",
        token=token,
    )
    item_rows = _must(status, items)
    assert isinstance(item_rows, list)
    empty = 0
    for item in item_rows:
        text = str(item.get("question_text") or "").strip()
        print(
            f"ITEM {item.get('label')} status={item.get('status')} "
            f"text_len={len(text)} key={item.get('question_key')}"
        )
        if text:
            continue
        empty += 1
        status, _excluded = _request(
            "PATCH",
            f"/exams/{EXAM_ID}/question-recognition-items/{item['id']}",
            token=token,
            json_body={"status": "excluded"},
        )
        _must(status, _excluded)
    print(f"EXCLUDED_EMPTY {empty}/{len(item_rows)}")

    status, confirm = _request(
        "POST",
        f"/exams/{EXAM_ID}/question-recognition-runs/{RUN_ID}/confirm",
        token=token,
    )
    confirm_data = _must(status, confirm)
    assert isinstance(confirm_data, dict)
    print(f"CONFIRMED_AT {confirm_data.get('confirmed_at')}")
    linked = print_knowledge_links(EXAM_ID)
    print(json.dumps({"exam_id": EXAM_ID, "student_email": STUDENT_EMAIL, "linked": linked}))
    return 0 if linked else 3


if __name__ == "__main__":
    sys.exit(main())
