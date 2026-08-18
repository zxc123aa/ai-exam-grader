import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import Organization, UserRole
from tests.api.routes.test_students_wrongbook import _headers, _user
from tests.utils.utils import random_lower_string


@pytest.fixture(autouse=True)
def _isolated_snap_cache(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """snap 结果按图片哈希落盘缓存，测试间要隔离，否则串结果。"""
    monkeypatch.setattr(settings, "STORAGE_CACHE_DIR", str(tmp_path))


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00"
    b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _student_headers(client: TestClient, db: Session, name: str) -> dict[str, str]:
    org = Organization(name=f"拍题学校-{name}", code=f"snap-{random_lower_string()}")
    db.add(org)
    db.commit()
    db.refresh(org)
    user, password = _user(db, UserRole.STUDENT, org)
    return _headers(client, user, password)


def _teacher_headers(client: TestClient, db: Session, name: str) -> dict[str, str]:
    org = Organization(
        name=f"拍题教师学校-{name}", code=f"snap-t-{random_lower_string()}"
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    user, password = _user(db, UserRole.TEACHER, org)
    return _headers(client, user, password)


def _post_snap(
    client: TestClient,
    headers: dict[str, str],
    *,
    image: bytes = PNG_BYTES,
    mode: str = "solve",
    max_score: float | None = None,
):
    data: dict[str, str] = {"mode": mode}
    if max_score is not None:
        data["max_score"] = str(max_score)
    return client.post(
        f"{settings.API_V1_STR}/students/me/snap",
        headers=headers,
        files={"image": ("question.png", image, "image/png")},
        data=data,
    )


def test_snap_solve_returns_answer_and_explanation(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = _student_headers(client, db, "答疑")
    calls: list[dict] = []
    payloads = [
        {"question_text": "已知物体质量 2kg，求重力加速度为 10 时的重力。"},
        {"answer": "20N", "explanation": "重力 G=mg=2×10=20N。"},
    ]

    def fake_call_json_model(**kwargs: object) -> tuple[dict, str, int]:
        calls.append(kwargs)
        return payloads[len(calls) - 1], "mock-model", 1

    monkeypatch.setattr("app.api.routes.students.call_json_model", fake_call_json_model)

    response = _post_snap(client, headers, mode="solve")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "solve"
    assert body["question_text"] == "已知物体质量 2kg，求重力加速度为 10 时的重力。"
    assert body["answer"] == "20N"
    assert body["explanation"] == "重力 G=mg=2×10=20N。"
    # 两次调用：视觉转录 + 解题
    assert len(calls) == 2
    assert "image_url" in str(calls[0]["messages"])
    assert "20N" not in str(calls[0]["messages"])


def test_snap_grade_returns_score_and_comment(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = _student_headers(client, db, "批改")
    monkeypatch.setattr(
        "app.api.routes.students._snap_extract_multi",
        lambda *args, **kwargs: [("计算 3+4×2。", "3+4×2=14")],
    )
    calls: list[dict] = []

    def fake_call_json_model(**kwargs: object) -> tuple[dict, str, int]:
        calls.append(kwargs)
        return (
            {"items": [{"score": 99, "comment": "运算顺序错了，应先算乘法。"}]},
            "mock-model",
            1,
        )

    monkeypatch.setattr("app.api.routes.students.call_json_model", fake_call_json_model)

    response = _post_snap(client, headers, mode="grade", max_score=10)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "grade"
    assert body["question_text"] == "计算 3+4×2。"
    assert body["student_answer"] == "3+4×2=14"
    # 模型给的分被钳制到满分 10
    assert body["score"] == 10
    assert body["max_score"] == 10
    assert body["comment"] == "运算顺序错了，应先算乘法。"
    assert len(body["items"]) == 1
    assert body["items"][0]["score"] == 10
    # 一次调用：多题合并解题+判分
    assert len(calls) == 1


def test_snap_grade_multiple_questions(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """整页多题：每题一条判分结果。"""
    headers = _student_headers(client, db, "多题")
    monkeypatch.setattr(
        "app.api.routes.students._snap_extract_multi",
        lambda *args, **kwargs: [
            ("计算 3+4×2。", "3+4×2=14"),
            ("计算 5×6。", "5×6=30"),
        ],
    )
    monkeypatch.setattr(
        "app.api.routes.students.call_json_model",
        lambda **kwargs: (
            {
                "items": [
                    {"score": 0, "comment": "先算乘法。"},
                    {"score": 10, "comment": "正确。"},
                ]
            },
            "mock-model",
            1,
        ),
    )
    response = _post_snap(client, headers, mode="grade", max_score=10)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["score"] == 0
    assert body["items"][1]["score"] == 10
    # 顶层字段是第一题，兼容旧前端
    assert body["score"] == 0


def test_snap_grade_without_student_answer_returns_422(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = _student_headers(client, db, "空作答")
    monkeypatch.setattr(
        "app.api.routes.students._snap_extract_multi",
        lambda *args, **kwargs: [("计算 3+4×2。", "")],
    )
    response = _post_snap(client, headers, mode="grade")
    assert response.status_code == 422, response.text
    assert "作答" in response.json()["detail"]


def test_snap_teacher_allowed(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """拍题答疑是无状态问答，教师/管理员也可用（试听识别效果）。"""
    headers = _teacher_headers(client, db, "教师")
    calls: list[dict] = []
    payloads = [
        {"question_text": "1+1=?"},
        {"answer": "2", "explanation": "加法。"},
    ]

    def fake_call_json_model(**kwargs: object) -> tuple[dict, str, int]:
        calls.append(kwargs)
        return payloads[len(calls) - 1], "mock-model", 1

    monkeypatch.setattr("app.api.routes.students.call_json_model", fake_call_json_model)
    response = _post_snap(client, headers)
    assert response.status_code == 200, response.text


def test_snap_oversized_image_returns_422(client: TestClient, db: Session) -> None:
    headers = _student_headers(client, db, "大图")
    big_image = PNG_BYTES + b"\x00" * (10 * 1024 * 1024)
    response = _post_snap(client, headers, image=big_image)
    assert response.status_code == 422, response.text
    assert "10MB" in response.json()["detail"]


def test_snap_invalid_mode_returns_422(client: TestClient, db: Session) -> None:
    headers = _student_headers(client, db, "坏模式")
    response = _post_snap(client, headers, mode="chat")
    assert response.status_code == 422, response.text


def test_snap_result_saved_to_wrongbook(client: TestClient, db: Session) -> None:
    """拍题内容可收进错题本，并出现在错题列表里。"""
    from tests.api.routes.test_students_learning_advice import _advice_context

    context = _advice_context(client, db, "收错题")
    created = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/from-snap",
        headers=context["headers"],
        json={
            "question_text": "计算 3+4×2。",
            "student_answer": "3+4×2=14",
            "comment": "运算顺序错了，应先算乘法。",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["question_text"] == "计算 3+4×2。"
    assert body["exam_title"] == "拍题答疑"

    listed = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries",
        headers=context["headers"],
    )
    assert listed.status_code == 200
    labels = [item["question_label"] for item in listed.json()["data"]]
    assert "拍题" in labels


def test_snap_records_saved_and_visible_only_to_owner(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """拍题结果留档成历史记录：列表+详情可查，他人不可见。"""
    headers = _student_headers(client, db, "历史")
    payloads = [
        {"question_text": "1+1 等于几？"},
        {"answer": "2", "explanation": "一加一等于二。"},
    ]
    calls: list[dict] = []

    def fake_call_json_model(**kwargs: object) -> tuple[dict, str, int]:
        calls.append(kwargs)
        return payloads[len(calls) - 1], "mock-model", 1

    monkeypatch.setattr("app.api.routes.students.call_json_model", fake_call_json_model)

    response = _post_snap(client, headers, mode="solve")
    assert response.status_code == 200, response.text

    listed = client.get(
        f"{settings.API_V1_STR}/students/me/snap/records", headers=headers
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()
    assert len(items) == 1
    assert items[0]["mode"] == "solve"
    assert "1+1" in items[0]["title"]

    detail = client.get(
        f"{settings.API_V1_STR}/students/me/snap/records/{items[0]['id']}",
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["payload"]["answer"] == "2"

    other = _student_headers(client, db, "旁人")
    forbidden = client.get(
        f"{settings.API_V1_STR}/students/me/snap/records/{items[0]['id']}",
        headers=other,
    )
    assert forbidden.status_code == 404
    empty = client.get(f"{settings.API_V1_STR}/students/me/snap/records", headers=other)
    assert empty.json() == []


def test_snap_stream_saves_solved_answers_to_records(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """流式答疑结束后，完整流出的解答进拍题历史。"""
    from app.models import (
        ProviderChannel,
        ProviderChannelKind,
        ProviderChannelStatus,
        ProviderProtocol,
    )
    from app.services.provider_gateway import RuntimeTarget

    headers = _student_headers(client, db, "流式历史")
    monkeypatch.setattr(
        "app.api.routes.students._snap_extract_questions",
        lambda *args, **kwargs: ["计算 3+4。"],
    )
    channel = ProviderChannel(
        code="snap-stream-test",
        display_name="流式测试渠道",
        kind=ProviderChannelKind.AUTHORIZED_RELAY,
        protocol=ProviderProtocol.OPENAI_CHAT,
        base_url="https://relay.example/v1",
        status=ProviderChannelStatus.ACTIVE,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    target = RuntimeTarget(
        provider="snap-stream-test",
        canonical_model="test-solver",
        upstream_model="upstream-solver",
        base_url="https://relay.example/v1",
        api_key="test-key",
        protocol=ProviderProtocol.OPENAI_CHAT,
        channel_id=channel.id,
        route_policy_id=None,
        route_version_id=None,
        max_concurrency=8,
        timeout_seconds=60,
    )
    monkeypatch.setattr(
        "app.api.routes.students.provider_gateway.resolve_channel_target",
        lambda *args, **kwargs: target,
    )
    monkeypatch.setattr(
        "app.api.routes.students.get_grading_defaults",
        lambda session: {
            "grading_provider": "snap-stream-test",
            "grading_model": "test-solver",
            "vision_provider": "snap-stream-test",
            "vision_model": "test-vision",
            "fallback_models": [],
        },
    )

    class _FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"3+4="}}]}'
            yield 'data: {"choices":[{"delta":{"content":"7"}}]}'
            yield "data: [DONE]"

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, *args, **kwargs):
            return _FakeStreamResponse()

    monkeypatch.setattr("app.api.routes.students.httpx.AsyncClient", _FakeClient)

    response = client.post(
        f"{settings.API_V1_STR}/students/me/snap/stream",
        headers=headers,
        files={"image": ("question.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200, response.text
    assert "3+4=" in response.text

    listed = client.get(
        f"{settings.API_V1_STR}/students/me/snap/records", headers=headers
    )
    items = listed.json()
    assert len(items) == 1
    assert "3+4" in items[0]["title"]
    detail = client.get(
        f"{settings.API_V1_STR}/students/me/snap/records/{items[0]['id']}",
        headers=headers,
    )
    payload = detail.json()["payload"]
    assert payload["kind"] == "solve"
    assert payload["items"] == [{"question": "计算 3+4。", "answer": "3+4=7"}]


def test_snap_grade_stream_grades_item_by_item_and_saves_record(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """拍照批改流式版：逐题出分，失败题不拖垮整页，结果进拍题历史。"""
    headers = _student_headers(client, db, "流式批改")
    monkeypatch.setattr(
        "app.api.routes.students._snap_extract_multi",
        lambda *args, **kwargs: [("计算 3+4。", "7"), ("计算 5-2。", "2")],
    )
    grade_calls: list[str] = []

    def fake_call_json_model(**kwargs: object):
        messages = kwargs["messages"]
        prompt = str(messages[0]["content"])  # type: ignore[index]
        grade_calls.append(prompt)
        if "3+4" in prompt:
            return {"score": 10, "comment": "正确。"}, "mock-model", 1
        return {"score": 0, "comment": "5-2=3，不是 2。"}, "mock-model", 1

    monkeypatch.setattr("app.api.routes.students.call_json_model", fake_call_json_model)

    response = client.post(
        f"{settings.API_V1_STR}/students/me/snap/grade/stream",
        headers=headers,
        files={"image": ("question.png", PNG_BYTES, "image/png")},
        data={"max_score": "10"},
    )
    assert response.status_code == 200, response.text
    body = response.text
    assert '"type": "grade-questions"' in body or '"type":"grade-questions"' in body
    assert body.count('grade-item"') == 2  # 两题各一张结果卡
    assert "正确。" in body and "5-2=3" in body

    listed = client.get(
        f"{settings.API_V1_STR}/students/me/snap/records", headers=headers
    )
    items = listed.json()
    assert len(items) == 1
    assert items[0]["mode"] == "grade"
    detail = client.get(
        f"{settings.API_V1_STR}/students/me/snap/records/{items[0]['id']}",
        headers=headers,
    )
    payload = detail.json()["payload"]
    assert payload["kind"] == "grade"
    assert len(payload["result"]["items"]) == 2
    assert payload["result"]["items"][0]["score"] == 10
