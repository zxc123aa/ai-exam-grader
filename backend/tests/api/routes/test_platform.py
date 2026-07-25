"""阶段 3 测试：平台管理端点、学校设置端点、公开注册关闭、用户管理学校隔离。"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Exam,
    ExamQuestion,
    ExamQuestionStatus,
    Organization,
    StandardAnswer,
    StandardAnswerRevision,
    StandardAnswerRevisionStatus,
    SystemConfig,
    User,
    UserCreate,
    UserRole,
)
from app.services.system_config import get_grading_defaults
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

PLATFORM_URL = f"{settings.API_V1_STR}/platform"
ORG_URL = f"{settings.API_V1_STR}/org"


def _create_org(db: Session, name: str) -> Organization:
    org = Organization(name=name, code=f"org-{random_lower_string()[:16]}")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _create_user(
    db: Session, role: UserRole, org: Organization | None
) -> tuple[User, str]:
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(),
            password=password,
            role=role,
            org_id=org.id if org else None,
        ),
    )
    return user, password


def _headers(client: TestClient, user: User, password: str) -> dict[str, str]:
    return user_authentication_headers(
        client=client, email=user.email, password=password
    )


def _support_headers(client: TestClient, db: Session) -> dict[str, str]:
    support, password = _create_user(db, UserRole.PLATFORM_SUPPORT, None)
    return _headers(client, support, password)


# ---------- 平台端点权限矩阵 ----------


def test_support_can_read_orgs(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    org = _create_org(db, "运营可见学校")
    headers = _support_headers(client, db)

    r = client.get(f"{PLATFORM_URL}/orgs", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 1
    item = next(o for o in data["data"] if o["id"] == str(org.id))
    assert item["name"] == "运营可见学校"
    assert item["status"] == "active"
    assert item["exam_count"] == 0
    assert item["student_count"] == 0
    assert item["teacher_count"] == 0

    r = client.get(f"{PLATFORM_URL}/orgs/{org.id}", headers=headers)
    assert r.status_code == 200
    detail = r.json()
    assert detail["code"] == org.code
    assert detail["users"] == []


def test_support_cannot_write_orgs(client: TestClient, db: Session) -> None:
    org = _create_org(db, "运营不可写学校")
    headers = _support_headers(client, db)

    r = client.post(
        f"{PLATFORM_URL}/orgs",
        headers=headers,
        json={"name": "X", "code": f"code-{random_lower_string()[:8]}"},
    )
    assert r.status_code == 403

    r = client.patch(
        f"{PLATFORM_URL}/orgs/{org.id}", headers=headers, json={"status": "suspended"}
    )
    assert r.status_code == 403

    r = client.post(
        f"{PLATFORM_URL}/orgs/{org.id}/owners",
        headers=headers,
        json={"email": random_email(), "password": random_lower_string()},
    )
    assert r.status_code == 403


def test_school_roles_forbidden_from_platform(
    client: TestClient, db: Session
) -> None:
    org = _create_org(db, "学校角色禁入平台")
    owner, owner_pw = _create_user(db, UserRole.SCHOOL_OWNER, org)
    teacher, teacher_pw = _create_user(db, UserRole.TEACHER, org)
    for user, password in ((owner, owner_pw), (teacher, teacher_pw)):
        headers = _headers(client, user, password)
        r = client.get(f"{PLATFORM_URL}/orgs", headers=headers)
        assert r.status_code == 403
        r = client.get(f"{PLATFORM_URL}/orgs/{org.id}", headers=headers)
        assert r.status_code == 403


# ---------- 建学校 / 追加 owner ----------


def test_create_org_with_owner(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    owner_email = random_email()
    owner_password = random_lower_string()
    code = f"sch-{random_lower_string()[:12]}"
    r = client.post(
        f"{PLATFORM_URL}/orgs",
        headers=superuser_token_headers,
        json={
            "name": "测试一中",
            "code": code,
            "contact_name": "张三",
            "owner": {
                "email": owner_email,
                "full_name": "王校长",
                "password": owner_password,
            },
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "测试一中"
    assert data["code"] == code
    assert data["contact_name"] == "张三"
    assert data["status"] == "active"
    assert len(data["users"]) == 1
    assert data["users"][0]["email"] == owner_email
    assert data["users"][0]["role"] == UserRole.SCHOOL_OWNER

    # owner 可登录，且归属新学校
    owner = crud.get_user_by_email(session=db, email=owner_email)
    assert owner
    assert owner.role == UserRole.SCHOOL_OWNER
    assert str(owner.org_id) == data["id"]
    headers = user_authentication_headers(
        client=client, email=owner_email, password=owner_password
    )
    r = client.get(f"{settings.API_V1_STR}/users/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["org_name"] == "测试一中"


def test_create_org_without_owner(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{PLATFORM_URL}/orgs",
        headers=superuser_token_headers,
        json={"name": "无账号学校", "code": f"sch-{random_lower_string()[:12]}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["users"] == []


def test_create_org_duplicate_code_409(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    code = f"sch-{random_lower_string()[:12]}"
    payload = {"name": "学校甲", "code": code}
    r = client.post(
        f"{PLATFORM_URL}/orgs", headers=superuser_token_headers, json=payload
    )
    assert r.status_code == 200
    r = client.post(
        f"{PLATFORM_URL}/orgs",
        headers=superuser_token_headers,
        json={"name": "学校乙", "code": code},
    )
    assert r.status_code == 409


def test_create_org_owner_email_conflict_rolls_back(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    # owner 邮箱已存在时整个创建失败，学校不落库（事务一致）
    existing, _ = _create_user(db, UserRole.TEACHER, None)
    code = f"sch-{random_lower_string()[:12]}"
    r = client.post(
        f"{PLATFORM_URL}/orgs",
        headers=superuser_token_headers,
        json={
            "name": "回滚学校",
            "code": code,
            "owner": {"email": existing.email, "password": random_lower_string()},
        },
    )
    assert r.status_code == 400
    org = db.exec(select(Organization).where(Organization.code == code)).first()
    assert org is None


def test_update_org_status_and_info(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    org = _create_org(db, "待停用学校")
    r = client.patch(
        f"{PLATFORM_URL}/orgs/{org.id}",
        headers=superuser_token_headers,
        json={"status": "suspended", "contact_name": "李四"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "suspended"
    assert data["contact_name"] == "李四"

    # 非法 status 被 schema 拒绝
    r = client.patch(
        f"{PLATFORM_URL}/orgs/{org.id}",
        headers=superuser_token_headers,
        json={"status": "deleted"},
    )
    assert r.status_code == 422


def test_org_not_found_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    missing = uuid.uuid4()
    r = client.get(f"{PLATFORM_URL}/orgs/{missing}", headers=superuser_token_headers)
    assert r.status_code == 404
    r = client.patch(
        f"{PLATFORM_URL}/orgs/{missing}",
        headers=superuser_token_headers,
        json={"name": "X"},
    )
    assert r.status_code == 404
    r = client.post(
        f"{PLATFORM_URL}/orgs/{missing}/owners",
        headers=superuser_token_headers,
        json={"email": random_email(), "password": random_lower_string()},
    )
    assert r.status_code == 404


def test_add_org_owner(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    org = _create_org(db, "追加 owner 学校")
    email = random_email()
    r = client.post(
        f"{PLATFORM_URL}/orgs/{org.id}/owners",
        headers=superuser_token_headers,
        json={"email": email, "full_name": "第二校长", "password": random_lower_string()},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == email
    assert data["role"] == UserRole.SCHOOL_OWNER

    user = crud.get_user_by_email(session=db, email=email)
    assert user
    assert user.org_id == org.id

    # 邮箱重复 → 400
    r = client.post(
        f"{PLATFORM_URL}/orgs/{org.id}/owners",
        headers=superuser_token_headers,
        json={"email": email, "password": random_lower_string()},
    )
    assert r.status_code == 400


def test_org_stats_counts(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    org = _create_org(db, "统计学校")
    owner, owner_pw = _create_user(db, UserRole.SCHOOL_OWNER, org)
    teacher, _ = _create_user(db, UserRole.TEACHER, org)
    headers = _headers(client, owner, owner_pw)

    r = client.post(
        f"{settings.API_V1_STR}/exams/", headers=headers, json={"title": "统计考试"}
    )
    assert r.status_code == 200
    r = client.post(
        f"{settings.API_V1_STR}/classes/", headers=headers, json={"name": "统计班"}
    )
    assert r.status_code == 200
    class_id = r.json()["id"]
    r = client.post(
        f"{settings.API_V1_STR}/classes/{class_id}/students/batch",
        headers=headers,
        json={"rows": [{"name": "学生一"}, {"name": "学生二"}]},
    )
    assert r.status_code == 200, r.text

    r = client.get(f"{PLATFORM_URL}/orgs/{org.id}", headers=superuser_token_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["exam_count"] == 1
    assert data["student_count"] == 2
    assert data["teacher_count"] == 2  # owner + teacher


# ---------- 学校设置端点 ----------


def test_org_settings_teacher_read_only(client: TestClient, db: Session) -> None:
    org = _create_org(db, "设置学校")
    teacher, teacher_pw = _create_user(db, UserRole.TEACHER, org)
    headers = _headers(client, teacher, teacher_pw)

    r = client.get(f"{ORG_URL}/settings", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "设置学校"
    assert data["code"] == org.code
    assert data["exam_sharing_enabled"] is False

    r = client.patch(
        f"{ORG_URL}/settings", headers=headers, json={"contact_name": "越权"}
    )
    assert r.status_code == 403


def test_org_settings_owner_can_write(client: TestClient, db: Session) -> None:
    org = _create_org(db, "可写设置学校")
    owner, owner_pw = _create_user(db, UserRole.SCHOOL_OWNER, org)
    headers = _headers(client, owner, owner_pw)

    r = client.patch(
        f"{ORG_URL}/settings",
        headers=headers,
        json={"contact_name": "赵六", "exam_sharing_enabled": True},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["contact_name"] == "赵六"
    assert data["exam_sharing_enabled"] is True

    db.refresh(org)
    assert org.contact_name == "赵六"
    assert org.exam_sharing_enabled is True


def test_org_settings_school_admin_read_only(client: TestClient, db: Session) -> None:
    org = _create_org(db, "admin 设置学校")
    admin, admin_pw = _create_user(db, UserRole.SCHOOL_ADMIN, org)
    headers = _headers(client, admin, admin_pw)
    r = client.get(f"{ORG_URL}/settings", headers=headers)
    assert r.status_code == 200
    r = client.patch(
        f"{ORG_URL}/settings", headers=headers, json={"contact_name": "越权"}
    )
    assert r.status_code == 403


def test_org_settings_student_forbidden(client: TestClient, db: Session) -> None:
    org = _create_org(db, "学生禁入学校")
    student, student_pw = _create_user(db, UserRole.STUDENT, org)
    headers = _headers(client, student, student_pw)
    r = client.get(f"{ORG_URL}/settings", headers=headers)
    assert r.status_code == 403
    r = client.patch(
        f"{ORG_URL}/settings", headers=headers, json={"contact_name": "越权"}
    )
    assert r.status_code == 403


# ---------- 公开注册关闭 ----------


def test_signup_closed(client: TestClient, db: Session) -> None:
    email = random_email()
    r = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={"email": email, "password": random_lower_string()},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "公开注册已关闭，请联系学校管理员创建账号"
    assert crud.get_user_by_email(session=db, email=email) is None


# ---------- 用户管理：学校隔离与角色上限 ----------


def test_users_list_scoped_to_own_org(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    org_a = _create_org(db, "隔离学校A")
    org_b = _create_org(db, "隔离学校B")
    owner_a, owner_a_pw = _create_user(db, UserRole.SCHOOL_OWNER, org_a)
    teacher_a, _ = _create_user(db, UserRole.TEACHER, org_a)
    teacher_b, _ = _create_user(db, UserRole.TEACHER, org_b)

    headers = _headers(client, owner_a, owner_a_pw)
    r = client.get(f"{settings.API_V1_STR}/users/", headers=headers)
    assert r.status_code == 200
    emails = {u["email"] for u in r.json()["data"]}
    assert owner_a.email in emails
    assert teacher_a.email in emails
    assert teacher_b.email not in emails
    # 看不到平台账号
    assert settings.FIRST_SUPERUSER not in emails

    # 平台超管看全部
    r = client.get(
        f"{settings.API_V1_STR}/users/", headers=superuser_token_headers
    )
    emails = {u["email"] for u in r.json()["data"]}
    assert teacher_b.email in emails
    assert settings.FIRST_SUPERUSER in emails


def test_school_owner_cannot_touch_other_org_user(
    client: TestClient, db: Session
) -> None:
    org_a = _create_org(db, "越权学校A")
    org_b = _create_org(db, "越权学校B")
    owner_a, owner_a_pw = _create_user(db, UserRole.SCHOOL_OWNER, org_a)
    teacher_b, _ = _create_user(db, UserRole.TEACHER, org_b)
    headers = _headers(client, owner_a, owner_a_pw)

    r = client.patch(
        f"{settings.API_V1_STR}/users/{teacher_b.id}",
        headers=headers,
        json={"full_name": "越权改名"},
    )
    assert r.status_code == 403

    r = client.delete(
        f"{settings.API_V1_STR}/users/{teacher_b.id}", headers=headers
    )
    assert r.status_code == 403


def test_school_admin_cannot_grant_owner_or_admin_role(
    client: TestClient, db: Session
) -> None:
    org = _create_org(db, "admin 上限学校")
    admin, admin_pw = _create_user(db, UserRole.SCHOOL_ADMIN, org)
    teacher, _ = _create_user(db, UserRole.TEACHER, org)
    headers = _headers(client, admin, admin_pw)

    # 不能把教师提升为 owner / admin
    r = client.patch(
        f"{settings.API_V1_STR}/users/{teacher.id}",
        headers=headers,
        json={"role": "school_owner"},
    )
    assert r.status_code == 403
    r = client.patch(
        f"{settings.API_V1_STR}/users/{teacher.id}",
        headers=headers,
        json={"role": "school_admin"},
    )
    assert r.status_code == 403

    # 不能创建 owner / admin 账号
    r = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=headers,
        json={
            "email": random_email(),
            "password": random_lower_string(),
            "role": "school_owner",
        },
    )
    assert r.status_code == 403

    # 可以创建普通教师（归入本校）
    r = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=headers,
        json={"email": random_email(), "password": random_lower_string()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["org_id"] == str(org.id)


def test_school_admin_cannot_modify_owner_account(
    client: TestClient, db: Session
) -> None:
    org = _create_org(db, "admin 不可动 owner 学校")
    admin, admin_pw = _create_user(db, UserRole.SCHOOL_ADMIN, org)
    owner, _ = _create_user(db, UserRole.SCHOOL_OWNER, org)
    headers = _headers(client, admin, admin_pw)
    r = client.patch(
        f"{settings.API_V1_STR}/users/{owner.id}",
        headers=headers,
        json={"full_name": "越权"},
    )
    assert r.status_code == 403


def test_cannot_change_own_role(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    superuser = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert superuser
    r = client.patch(
        f"{settings.API_V1_STR}/users/{superuser.id}",
        headers=superuser_token_headers,
        json={"role": "teacher"},
    )
    assert r.status_code == 400

    org = _create_org(db, "自改角色学校")
    owner, owner_pw = _create_user(db, UserRole.SCHOOL_OWNER, org)
    headers = _headers(client, owner, owner_pw)
    r = client.patch(
        f"{settings.API_V1_STR}/users/{owner.id}",
        headers=headers,
        json={"role": "teacher"},
    )
    assert r.status_code == 400


# ---------- 系统设置：模型与批改默认值 ----------

SYSTEM_CONFIG_URL = f"{PLATFORM_URL}/system-config"


def _clear_system_config(db: Session) -> None:
    for row in db.exec(select(SystemConfig)).all():
        db.delete(row)
    db.commit()


def test_system_config_superuser_only(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(SYSTEM_CONFIG_URL, headers=superuser_token_headers)
    assert r.status_code == 200

    support_headers = _support_headers(client, db)
    r = client.get(SYSTEM_CONFIG_URL, headers=support_headers)
    assert r.status_code == 403
    r = client.patch(
        SYSTEM_CONFIG_URL, headers=support_headers, json={"grading_model": "gpt-5.5"}
    )
    assert r.status_code == 403

    org = _create_org(db, "系统设置禁入学校")
    owner, owner_pw = _create_user(db, UserRole.SCHOOL_OWNER, org)
    owner_headers = _headers(client, owner, owner_pw)
    r = client.get(SYSTEM_CONFIG_URL, headers=owner_headers)
    assert r.status_code == 403


def test_system_config_env_defaults_and_provider_status(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    _clear_system_config(db)
    r = client.get(SYSTEM_CONFIG_URL, headers=superuser_token_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["vision_provider"] == settings.VISION_DEFAULT_PROVIDER
    assert data["vision_model"] == settings.VISION_DEFAULT_MODEL
    assert data["grading_provider"] == settings.GRADING_DEFAULT_PROVIDER
    assert data["grading_model"] == settings.GRADING_DEFAULT_MODEL
    assert data["fallback_models"] == [
        item.strip()
        for item in settings.VISION_FALLBACK_MODELS.split(",")
        if item.strip()
    ]
    assert data["review_threshold"] == 0.8
    assert data["max_concurrency"] == 8

    statuses = {item["name"]: item["configured"] for item in data["providers"]}
    assert statuses == {
        "pomoai": bool(settings.PROVIDER_POMOAI_API_KEY.strip()),
        "fluxnode_gemini": bool(settings.PROVIDER_FLUXNODE_GEMINI_API_KEY.strip()),
        "fluxnode_grok": bool(settings.PROVIDER_FLUXNODE_GROK_API_KEY.strip()),
        "kimi": bool(settings.PROVIDER_KIMI_API_KEY.strip()),
    }
    # 任何情况下都不回传 API Key
    assert "api_key" not in r.text and "API_KEY" not in r.text


def test_system_config_partial_update_and_validation(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    _clear_system_config(db)
    try:
        r = client.patch(
            SYSTEM_CONFIG_URL,
            headers=superuser_token_headers,
            json={"grading_model": "gpt-5.5", "review_threshold": 0.6},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # 更新的键生效，未提交的键保持 env 默认
        assert data["grading_model"] == "gpt-5.5"
        assert data["review_threshold"] == 0.6
        assert data["grading_provider"] == settings.GRADING_DEFAULT_PROVIDER
        assert data["vision_model"] == settings.VISION_DEFAULT_MODEL
        assert data["max_concurrency"] == 8

        # 再次 GET 读到 DB 持久化的值
        r = client.get(SYSTEM_CONFIG_URL, headers=superuser_token_headers)
        assert r.json()["grading_model"] == "gpt-5.5"

        # 未知 provider → 422
        r = client.patch(
            SYSTEM_CONFIG_URL,
            headers=superuser_token_headers,
            json={"grading_provider": "unknown"},
        )
        assert r.status_code == 422

        # provider/model 组合不匹配（kimi 没有 gemini-3.5-flash）→ 422
        r = client.patch(
            SYSTEM_CONFIG_URL,
            headers=superuser_token_headers,
            json={"vision_provider": "kimi"},
        )
        assert r.status_code == 422

        # 阈值 / 并发越界 → 422（schema 校验）
        r = client.patch(
            SYSTEM_CONFIG_URL,
            headers=superuser_token_headers,
            json={"review_threshold": 1.5},
        )
        assert r.status_code == 422
        r = client.patch(
            SYSTEM_CONFIG_URL,
            headers=superuser_token_headers,
            json={"max_concurrency": 0},
        )
        assert r.status_code == 422
    finally:
        _clear_system_config(db)


def test_grading_run_uses_system_config_defaults(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """DB 里的默认值优先于 env；请求未显式给的字段全部走系统设置。"""
    _clear_system_config(db)
    superuser = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert superuser
    default_org_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    try:
        r = client.patch(
            SYSTEM_CONFIG_URL,
            headers=superuser_token_headers,
            json={
                "grading_provider": "kimi",
                "grading_model": "kimi-k2.6",
                "fallback_models": ["kimi-k2.5"],
                "review_threshold": 0.55,
                "max_concurrency": 3,
            },
        )
        assert r.status_code == 200, r.text

        exam = Exam(
            title="默认值考试",
            owner_id=superuser.id,
            org_id=default_org_id,
        )
        db.add(exam)
        db.commit()
        db.refresh(exam)
        question = ExamQuestion(
            exam_id=exam.id,
            question_key="1",
            label="第1题",
            question_text="1+1=?",
            status=ExamQuestionStatus.CONFIRMED,
        )
        db.add(question)
        db.commit()
        db.refresh(question)
        answer = StandardAnswer(
            exam_id=exam.id,
            question_id=question.id,
            answer_text="2",
            max_score=5,
        )
        db.add(answer)
        db.commit()
        db.refresh(answer)
        revision = StandardAnswerRevision(
            standard_answer_id=answer.id,
            question_id=question.id,
            revision_number=1,
            question_key="1",
            question_text="1+1=?",
            answer_text="2",
            max_score=5,
            content_hash="a" * 64,
            status=StandardAnswerRevisionStatus.PUBLISHED,
            created_by_id=superuser.id,
        )
        db.add(revision)
        db.commit()
        db.refresh(revision)
        answer.current_revision_id = revision.id
        db.add(answer)
        db.commit()

        r = client.post(
            f"{settings.API_V1_STR}/grading/runs",
            headers=superuser_token_headers,
            json={"exam_id": str(exam.id)},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["provider"] == "kimi"
        assert data["model"] == "kimi-k2.6"
        assert data["fallback_models"] == ["kimi-k2.5"]
        snapshot = data["config_snapshot"]
        assert snapshot["review_threshold"] == 0.55
        assert snapshot["max_concurrency"] == 3
        assert snapshot["max_parallel_submissions"] == 3
        assert snapshot["max_concurrency_per_submission"] == 1
        assert snapshot["vision_provider"] == settings.VISION_DEFAULT_PROVIDER
        assert snapshot["vision_model"] == settings.VISION_DEFAULT_MODEL

        r = client.post(
            f"{settings.API_V1_STR}/grading/runs",
            headers=superuser_token_headers,
            json={
                "exam_id": str(exam.id),
                "max_parallel_submissions": 3,
                "max_concurrency_per_submission": 5,
            },
        )
        assert r.status_code == 200, r.text
        explicit_snapshot = r.json()["config_snapshot"]
        assert explicit_snapshot["max_parallel_submissions"] == 3
        assert explicit_snapshot["max_concurrency_per_submission"] == 5
        assert explicit_snapshot["max_concurrency"] == 15
    finally:
        _clear_system_config(db)


def test_get_grading_defaults_env_fallback(db: Session) -> None:
    _clear_system_config(db)
    defaults = get_grading_defaults(db)
    assert defaults["grading_provider"] == settings.GRADING_DEFAULT_PROVIDER
    assert defaults["grading_model"] == settings.GRADING_DEFAULT_MODEL
    assert defaults["vision_provider"] == settings.VISION_DEFAULT_PROVIDER
    assert defaults["review_threshold"] == 0.8
    assert defaults["max_concurrency"] == 32


def test_system_config_pipeline_keys(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """region/recognition 四键：缺键回落 vision 默认，PATCH 生效并校验组合。"""
    _clear_system_config(db)
    try:
        r = client.get(SYSTEM_CONFIG_URL, headers=superuser_token_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["region_provider"] == settings.VISION_DEFAULT_PROVIDER
        assert data["region_model"] == settings.VISION_DEFAULT_MODEL
        assert data["recognition_provider"] == settings.VISION_DEFAULT_PROVIDER
        assert data["recognition_model"] == settings.VISION_DEFAULT_MODEL

        defaults = get_grading_defaults(db)
        assert defaults["region_model"] == settings.VISION_DEFAULT_MODEL
        assert defaults["recognition_model"] == settings.VISION_DEFAULT_MODEL

        r = client.patch(
            SYSTEM_CONFIG_URL,
            headers=superuser_token_headers,
            json={
                "region_provider": "kimi",
                "region_model": "kimi-k2.6",
                "recognition_provider": "pomoai",
                "recognition_model": "gpt-5.5",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["region_provider"] == "kimi"
        assert data["region_model"] == "kimi-k2.6"
        assert data["recognition_provider"] == "pomoai"
        assert data["recognition_model"] == "gpt-5.5"

        r = client.get(SYSTEM_CONFIG_URL, headers=superuser_token_headers)
        assert r.json()["recognition_model"] == "gpt-5.5"

        # region 组合不匹配（kimi 没有 gemini-3.5-flash）→ 422
        r = client.patch(
            SYSTEM_CONFIG_URL,
            headers=superuser_token_headers,
            json={"region_provider": "kimi", "region_model": "gemini-3.5-flash"},
        )
        assert r.status_code == 422
        # recognition 未知 provider → 422
        r = client.patch(
            SYSTEM_CONFIG_URL,
            headers=superuser_token_headers,
            json={"recognition_provider": "unknown"},
        )
        assert r.status_code == 422
    finally:
        _clear_system_config(db)
