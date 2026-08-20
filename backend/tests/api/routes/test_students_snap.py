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
        lambda *args, **kwargs: [("计算 3+4×2。", "3+4×2=14", None)],
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
            ("计算 3+4×2。", "3+4×2=14", 5.0),
            ("计算 5×6。", "5×6=30", 4.0),
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
    # 卷面分值优先于默认满分：第二题卷面 4 分，模型给的 10 被钳到 4
    assert body["items"][0]["max_score"] == 5.0
    assert body["items"][1]["score"] == 4
    assert body["items"][1]["max_score"] == 4.0
    # 顶层字段是第一题，兼容旧前端
    assert body["score"] == 0


def test_snap_grade_without_student_answer_returns_422(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = _student_headers(client, db, "空作答")
    monkeypatch.setattr(
        "app.api.routes.students._snap_extract_multi",
        lambda *args, **kwargs: [("计算 3+4×2。", "", None)],
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
        lambda *args, **kwargs: [("计算 3+4。", "7", 6.0), ("计算 5-2。", "2", 4.0)],
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
    assert payload["result"]["items"][0]["score"] == 6  # 卷面 6 分封顶


def _fake_stream_target(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """给单题流式接口配一个假渠道+假目标，别碰真实上游。"""
    from app.models import (
        ProviderChannel,
        ProviderChannelKind,
        ProviderChannelStatus,
        ProviderProtocol,
    )
    from app.services.provider_gateway import RuntimeTarget

    channel = ProviderChannel(
        code=f"snap-one-{random_lower_string()[:8]}",
        display_name="单题测试渠道",
        kind=ProviderChannelKind.AUTHORIZED_RELAY,
        protocol=ProviderProtocol.OPENAI_CHAT,
        base_url="https://relay.example/v1",
        status=ProviderChannelStatus.ACTIVE,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    target = RuntimeTarget(
        provider=channel.code,
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
            "grading_provider": channel.code,
            "grading_model": "test-solver",
            "vision_provider": channel.code,
            "vision_model": "test-vision",
            "fallback_models": [],
            "vision_fallback_models": [],
        },
    )


class _FakeStreamResponse:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aiter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"答案是 7"}}]}'
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


def test_snap_solve_one_stream_retries_single_question(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """单题解答重试：流式返回这一题的解答。"""
    headers = _student_headers(client, db, "单题解答")
    _fake_stream_target(db, monkeypatch)
    monkeypatch.setattr("app.api.routes.students.httpx.AsyncClient", _FakeClient)

    response = client.post(
        f"{settings.API_V1_STR}/students/me/snap/solve-one/stream",
        headers=headers,
        json={"question_text": "计算 3+4。"},
    )
    assert response.status_code == 200, response.text
    assert "答案是 7" in response.text
    assert '"done"' in response.text


def test_snap_grade_one_regrades_single_question(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """单题批改重试：只重判这一题，返回分数和评语。"""
    headers = _student_headers(client, db, "单题批改")

    def fake_call_json_model(**_kwargs: object):
        return {"score": 6, "comment": "过程对了一半。"}, "mock-model", 1

    monkeypatch.setattr("app.api.routes.students.call_json_model", fake_call_json_model)

    response = client.post(
        f"{settings.API_V1_STR}/students/me/snap/grade-one",
        headers=headers,
        json={
            "question_text": "计算 3+4×2。",
            "student_answer": "3+4×2=14",
            "max_score": 10,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["score"] == 6
    assert body["max_score"] == 10
    assert body["comment"] == "过程对了一半。"


def test_snap_record_delete_owner_only(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """拍题记录可删除：只能删自己的，删完列表里没了。"""
    headers = _student_headers(client, db, "删记录")
    payloads = [
        {"question_text": "2+2 等于几？"},
        {"answer": "4", "explanation": "二加二等于四。"},
    ]
    calls: list[dict] = []

    def fake_call_json_model(**kwargs: object) -> tuple[dict, str, int]:
        calls.append(kwargs)
        return payloads[len(calls) - 1], "mock-model", 1

    monkeypatch.setattr("app.api.routes.students.call_json_model", fake_call_json_model)
    assert _post_snap(client, headers, mode="solve").status_code == 200

    items = client.get(
        f"{settings.API_V1_STR}/students/me/snap/records", headers=headers
    ).json()
    assert len(items) == 1
    record_id = items[0]["id"]

    other = _student_headers(client, db, "删旁人")
    assert (
        client.delete(
            f"{settings.API_V1_STR}/students/me/snap/records/{record_id}",
            headers=other,
        ).status_code
        == 404
    )

    assert (
        client.delete(
            f"{settings.API_V1_STR}/students/me/snap/records/{record_id}",
            headers=headers,
        ).status_code
        == 204
    )
    assert (
        client.get(
            f"{settings.API_V1_STR}/students/me/snap/records", headers=headers
        ).json()
        == []
    )


def test_snap_wrongbook_entry_gets_knowledge_points(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """拍题收进错题本时自动标注知识点，进掌握度统计。"""
    from tests.api.routes.test_students_learning_advice import _advice_context

    def fake_call_json_model(**_kwargs: object):
        return {"knowledge_points": ["一元一次方程"]}, "mock-model", 1

    monkeypatch.setattr("app.api.routes.students.call_json_model", fake_call_json_model)

    context = _advice_context(client, db, "知识点")
    created = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/from-snap",
        headers=context["headers"],
        json={
            "question_text": "解方程 2x+3=7。",
            "student_answer": "x=3",
            "comment": "移项错了",
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["knowledge_point_names"] == ["一元一次方程"]

    # 掌握度统计里能看到这个知识点
    mastery = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/mastery",
        headers=context["headers"],
    )
    assert mastery.status_code == 200
    names = [item["knowledge_point_name"] for item in mastery.json()["data"]]
    assert "一元一次方程" in names


def test_wrongbook_entry_delete_and_collections(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """错题可删除；错题集 CRUD + 移入/移出 + 列表按集过滤。"""
    from tests.api.routes.test_students_learning_advice import _advice_context

    monkeypatch.setattr(
        "app.api.routes.students.call_json_model",
        lambda **_kwargs: ({"knowledge_points": ["运算"]}, "mock-model", 1),
    )
    context = _advice_context(client, db, "错题集")
    headers = context["headers"]
    created = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/from-snap",
        headers=headers,
        json={
            "question_text": "计算 3+4×2。",
            "student_answer": "14",
            "comment": "运算顺序错",
        },
    )
    assert created.status_code == 200, created.text
    entry_id = created.json()["entry_id"]

    # 建集 + 移入
    col = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/collections",
        headers=headers,
        json={"name": "计算专题"},
    )
    assert col.status_code == 200, col.text
    col_id = col.json()["id"]
    added = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/collections/{col_id}/entries",
        headers=headers,
        json={"entry_id": entry_id},
    )
    assert added.status_code == 200, added.text
    assert added.json()["entry_count"] == 1

    # 按集过滤能查到；按另一个空集过滤查不到
    in_col = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries?collection_id={col_id}",
        headers=headers,
    )
    assert any(i["entry_id"] == entry_id for i in in_col.json()["data"])
    empty_col = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/collections",
        headers=headers,
        json={"name": "空集"},
    ).json()["id"]
    not_in = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries?collection_id={empty_col}",
        headers=headers,
    )
    assert not any(i["entry_id"] == entry_id for i in not_in.json()["data"])

    # 移出 → 列表计数回落
    assert (
        client.delete(
            f"{settings.API_V1_STR}/students/me/wrongbook/collections/{col_id}/entries/{entry_id}",
            headers=headers,
        ).status_code
        == 204
    )
    cols = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/collections", headers=headers
    ).json()
    assert next(c for c in cols if c["id"] == col_id)["entry_count"] == 0

    # 删错题：之后列表里没了
    assert (
        client.delete(
            f"{settings.API_V1_STR}/students/me/wrongbook/entries/{entry_id}",
            headers=headers,
        ).status_code
        == 204
    )
    remaining = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries", headers=headers
    ).json()["data"]
    assert not any(i["entry_id"] == entry_id for i in remaining)

    # 别人的集/条目碰不到
    other = _student_headers(client, db, "错题集旁人")
    assert (
        client.delete(
            f"{settings.API_V1_STR}/students/me/wrongbook/collections/{col_id}",
            headers=other,
        ).status_code
        == 404
    )


def test_snap_grade_stream_marks_unanswered_without_model_call(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未作答的题直接出 0 分卡（不调模型），其余题正常判分。"""
    headers = _student_headers(client, db, "未作答")
    monkeypatch.setattr(
        "app.api.routes.students._snap_extract_multi",
        lambda *args, **kwargs: [
            ("计算 3+4。", "7", 5.0),
            ("应用题第 9 题。", "未作答", 5.0),
        ],
    )
    calls: list[str] = []

    def fake_call_json_model(**kwargs: object):
        messages = kwargs["messages"]
        calls.append(str(messages[0]["content"]))  # type: ignore[index]
        return {"score": 5, "comment": "正确。"}, "mock-model", 1

    monkeypatch.setattr("app.api.routes.students.call_json_model", fake_call_json_model)

    response = client.post(
        f"{settings.API_V1_STR}/students/me/snap/grade/stream",
        headers=headers,
        files={"image": ("question.png", PNG_BYTES, "image/png")},
        data={"max_score": "5"},
    )
    assert response.status_code == 200, response.text
    body = response.text
    assert "未作答，记 0 分" in body
    assert len(calls) == 1  # 只有有作答的那题调了模型
    assert "3+4" in calls[0]


def test_grade_one_cache_same_answer_same_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一（题目+作答+满分）连判两次必须同分：第二次走缓存不调模型。"""
    from app.api.routes.students import _snap_grade_one

    defaults = {
        "grading_provider": "pomoai",
        "grading_model": "gpt-5.6-sol",
        "fallback_models": [],
    }
    calls: list[int] = []
    scores = iter([3, 9])  # 模型若被调两次会给不同分

    def fake_call_json_model(**_kwargs: object):
        calls.append(1)
        return {"score": next(scores), "comment": "点评"}, "mock-model", 1

    monkeypatch.setattr("app.api.routes.students.call_json_model", fake_call_json_model)

    first = _snap_grade_one(
        question_text="计算 3+4。",
        student_answer="7",
        max_score=5,
        defaults=defaults,
    )
    second = _snap_grade_one(
        question_text="计算 3+4。",
        student_answer="7",
        max_score=5,
        defaults=defaults,
    )
    assert first["score"] == 3
    assert second["score"] == 3  # 缓存命中，不是 9
    assert len(calls) == 1


def test_snap_grade_stream_marks_drawing_for_manual_review(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """绘图作答标「请人工评分」，不硬判、不调模型。"""
    headers = _student_headers(client, db, "绘图")
    monkeypatch.setattr(
        "app.api.routes.students._snap_extract_multi",
        lambda *args, **kwargs: [("作图题：画出对称轴。", "绘图作答", 5.0)],
    )
    calls: list[str] = []
    monkeypatch.setattr(
        "app.api.routes.students.call_json_model",
        lambda **kwargs: calls.append(1) or ({"score": 5, "comment": "x"}, "m", 1),
    )

    response = client.post(
        f"{settings.API_V1_STR}/students/me/snap/grade/stream",
        headers=headers,
        files={"image": ("question.png", PNG_BYTES, "image/png")},
        data={"max_score": "5"},
    )
    assert response.status_code == 200, response.text
    assert "请对照原卷人工评分" in response.text
    assert not calls  # 绘图题不调模型


def test_full_score_snap_entry_not_marked_wrong(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """满分收藏不算错题：不污染掌握度（#01）。"""
    from tests.api.routes.test_students_learning_advice import _advice_context

    monkeypatch.setattr(
        "app.api.routes.students.call_json_model",
        lambda **_kwargs: ({"knowledge_points": []}, "mock-model", 1),
    )
    context = _advice_context(client, db, "满分收藏")
    created = client.post(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries/from-snap",
        headers=context["headers"],
        json={
            "question_text": "计算 3+4。",
            "student_answer": "7",
            "comment": "正确",
            "score": 5,
            "max_score": 5,
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["is_wrong"] is False

    # 默认错题列表（wrong_only）不应出现满分收藏
    listed = client.get(
        f"{settings.API_V1_STR}/students/me/wrongbook/entries",
        headers=context["headers"],
    ).json()["data"]
    assert not any(i["entry_id"] == created.json()["entry_id"] for i in listed)


def test_standard_answer_backfills_final_answer_when_only_explanation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模型只给过程没给最终答案时，自动用过程补出最终答案（#02）。"""
    from app.api.routes.students import _snap_standard_answer

    payloads = [
        {"answer": "", "explanation": "先算 4×2=8，再算 3+8。"},  # 第一次：只有过程
        {"answer": "11"},  # 补救调用：只要最终答案
    ]
    calls: list[dict] = []

    def fake_call_json_model(**kwargs: object):
        calls.append(kwargs)
        return payloads[len(calls) - 1], "mock-model", 1

    monkeypatch.setattr("app.api.routes.students.call_json_model", fake_call_json_model)

    answer, explanation = _snap_standard_answer(
        "计算 3+4×2。",
        {"grading_provider": "p", "grading_model": "m", "fallback_models": []},
    )
    assert answer == "11"
    assert "4×2=8" in explanation
    assert len(calls) == 2
