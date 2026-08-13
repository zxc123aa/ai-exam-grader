import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    AddonSku,
    AnswerQuotaGrant,
    BillingRateVersion,
    CommerceOrder,
    CommerceOrderStatus,
    Organization,
    OrganizationSubscription,
    PlanVersion,
    SubscriptionStatus,
    User,
    UserCreate,
    UserRole,
)
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

BASE = f"{settings.API_V1_STR}/commerce"


def seed_catalog(db: Session) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    plan_code = f"pilot-{suffix}"
    addon_code = f"answers-{suffix}"
    if not db.exec(select(BillingRateVersion)).first():
        db.add(
            BillingRateVersion(
                version=f"commerce-{uuid.uuid4().hex[:8]}",
                effective_at=datetime.now(UTC),
                input_microcredits_per_million=1,
                output_microcredits_per_million=1,
                image_microcredits_per_million=1,
            )
        )
    db.add(
        PlanVersion(
            code=plan_code,
            version=1,
            display_name="试点年度版",
            annual_price_cents=99_900,
            included_answers=10_000,
            published=True,
        )
    )
    db.add(
        AddonSku(
            code=addon_code,
            display_name="5000 份答卷加量包",
            answer_quota=5_000,
            price_cents=19_900,
            published=True,
        )
    )
    db.commit()
    return plan_code, addon_code


def create_school_owner_headers(
    client: TestClient, db: Session, org_id: uuid.UUID
) -> dict[str, str]:
    if not db.get(Organization, org_id):
        db.add(
            Organization(
                id=org_id,
                name=f"隔离测试学校-{str(org_id)[-4:]}",
                code=f"isolation-{str(org_id)[-4:]}",
            )
        )
        db.commit()
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(),
            password=password,
            role=UserRole.SCHOOL_OWNER,
            org_id=org_id,
        ),
    )
    return user_authentication_headers(
        client=client, email=user.email, password=password
    )


def create_order(client: TestClient, headers: dict[str, str], plan_code: str) -> dict:
    response = client.post(
        f"{BASE}/orders",
        headers=headers,
        json={
            "idempotency_key": f"order-{uuid.uuid4()}",
            "items": [{"item_type": "plan", "code": plan_code, "quantity": 1}],
        },
    )
    assert response.status_code == 200
    return response.json()


def test_order_creation_is_idempotent(
    client: TestClient,
    db: Session,
    school_owner_token_headers: dict[str, str],
) -> None:
    plan_code, _addon_code = seed_catalog(db)
    payload = {
        "idempotency_key": f"order-{uuid.uuid4()}",
        "items": [{"item_type": "plan", "code": plan_code, "quantity": 1}],
    }
    first = client.post(
        f"{BASE}/orders", headers=school_owner_token_headers, json=payload
    )
    second = client.post(
        f"{BASE}/orders", headers=school_owner_token_headers, json=payload
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["amount_cents"] == 99_900


def test_bank_transfer_fulfills_order_exactly_once(
    client: TestClient,
    db: Session,
    school_owner_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    plan_code, _addon_code = seed_catalog(db)
    created = client.post(
        f"{BASE}/orders",
        headers=school_owner_token_headers,
        json={
            "idempotency_key": f"order-{uuid.uuid4()}",
            "items": [{"item_type": "plan", "code": plan_code, "quantity": 1}],
        },
    )
    order_id = created.json()["id"]
    payload = {"transaction_reference": f"bank-{uuid.uuid4()}"}

    first = client.post(
        f"{BASE}/orders/{order_id}/bank-transfer",
        headers=superuser_token_headers,
        json=payload,
    )
    second = client.post(
        f"{BASE}/orders/{order_id}/bank-transfer",
        headers=superuser_token_headers,
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == CommerceOrderStatus.FULFILLED
    order = db.get(CommerceOrder, uuid.UUID(order_id))
    grants = db.exec(
        select(AnswerQuotaGrant).where(AnswerQuotaGrant.org_id == order.org_id)
    ).all()
    matching = [row for row in grants if row.note == f"订单 {order.order_no} 自动履约"]
    assert len(matching) == 1
    assert matching[0].total_answers == 10_000


def test_school_cannot_read_another_school_order(
    client: TestClient,
    db: Session,
    school_owner_token_headers: dict[str, str],
) -> None:
    plan_code, _ = seed_catalog(db)
    order = create_order(client, school_owner_token_headers, plan_code)
    other_headers = create_school_owner_headers(
        client, db, uuid.UUID("00000000-0000-0000-0000-000000000002")
    )

    response = client.get(f"{BASE}/orders/{order['id']}", headers=other_headers)

    assert response.status_code == 404


def test_addon_requires_active_contract(
    client: TestClient,
    db: Session,
) -> None:
    _plan_code, addon_code = seed_catalog(db)
    org_id = uuid.uuid4()
    headers = create_school_owner_headers(client, db, org_id)

    response = client.post(
        f"{BASE}/orders",
        headers=headers,
        json={
            "idempotency_key": f"addon-{uuid.uuid4()}",
            "items": [{"item_type": "addon", "code": addon_code, "quantity": 1}],
        },
    )

    assert response.status_code == 409
    assert "年度服务套餐" in response.json()["detail"]


def test_renewal_preserves_remaining_contract_time(
    client: TestClient,
    db: Session,
    school_owner_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    plan_code, _ = seed_catalog(db)
    first = create_order(client, school_owner_token_headers, plan_code)
    client.post(
        f"{BASE}/orders/{first['id']}/bank-transfer",
        headers=superuser_token_headers,
        json={"transaction_reference": f"bank-{uuid.uuid4()}"},
    )
    first_subscription = db.exec(
        select(OrganizationSubscription).where(
            OrganizationSubscription.contract_no == f"ORDER-{first['order_no']}"
        )
    ).one()
    first_end = first_subscription.ends_at

    second = create_order(client, school_owner_token_headers, plan_code)
    response = client.post(
        f"{BASE}/orders/{second['id']}/bank-transfer",
        headers=superuser_token_headers,
        json={"transaction_reference": f"bank-{uuid.uuid4()}"},
    )

    assert response.status_code == 200
    renewed = db.exec(
        select(OrganizationSubscription).where(
            OrganizationSubscription.contract_no == f"ORDER-{second['order_no']}"
        )
    ).one()
    assert renewed.ends_at == first_end + timedelta(days=365)


def test_refund_restores_previous_subscription_and_is_idempotent(
    client: TestClient,
    db: Session,
    school_owner_user: tuple[User, str],
    school_owner_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    owner, _password = school_owner_user
    plan_code, _ = seed_catalog(db)
    first = create_order(client, school_owner_token_headers, plan_code)
    client.post(
        f"{BASE}/orders/{first['id']}/bank-transfer",
        headers=superuser_token_headers,
        json={"transaction_reference": f"bank-{uuid.uuid4()}"},
    )
    previous = db.exec(
        select(OrganizationSubscription).where(
            OrganizationSubscription.contract_no == f"ORDER-{first['order_no']}"
        )
    ).one()
    previous_end = previous.ends_at
    first_grants = db.exec(
        select(AnswerQuotaGrant).where(
            AnswerQuotaGrant.order_id == uuid.UUID(first["id"])
        )
    ).all()
    for grant in first_grants:
        db.delete(grant)
    db.commit()

    second = create_order(client, school_owner_token_headers, plan_code)
    client.post(
        f"{BASE}/orders/{second['id']}/bank-transfer",
        headers=superuser_token_headers,
        json={"transaction_reference": f"bank-{uuid.uuid4()}"},
    )
    request_body = {
        "order_id": second["id"],
        "amount_cents": second["amount_cents"],
        "reason": "学校重复续费",
    }
    first_request = client.post(
        f"{BASE}/refunds", headers=school_owner_token_headers, json=request_body
    )
    second_request = client.post(
        f"{BASE}/refunds", headers=school_owner_token_headers, json=request_body
    )
    assert first_request.status_code == 200
    assert second_request.json()["id"] == first_request.json()["id"]

    response = client.patch(
        f"{BASE}/admin/refunds/{first_request.json()['id']}",
        headers=superuser_token_headers,
        json={"status": "succeeded", "review_note": "原路退回"},
    )

    assert response.status_code == 200
    repeated = client.patch(
        f"{BASE}/admin/refunds/{first_request.json()['id']}",
        headers=superuser_token_headers,
        json={"status": "succeeded", "review_note": "重复通知"},
    )
    assert repeated.status_code == 200
    db.refresh(previous)
    assert previous.status == SubscriptionStatus.ACTIVE
    assert previous.ends_at == previous_end


def test_refund_is_blocked_after_quota_use(
    client: TestClient,
    db: Session,
    school_owner_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    plan_code, _ = seed_catalog(db)
    order = create_order(client, school_owner_token_headers, plan_code)
    client.post(
        f"{BASE}/orders/{order['id']}/bank-transfer",
        headers=superuser_token_headers,
        json={"transaction_reference": f"bank-{uuid.uuid4()}"},
    )
    grant = db.exec(
        select(AnswerQuotaGrant).where(
            AnswerQuotaGrant.order_id == uuid.UUID(order["id"])
        )
    ).one()
    grant.consumed_answers = 1
    db.add(grant)
    db.commit()
    requested = client.post(
        f"{BASE}/refunds",
        headers=school_owner_token_headers,
        json={
            "order_id": order["id"],
            "amount_cents": order["amount_cents"],
            "reason": "不再使用",
        },
    )

    response = client.patch(
        f"{BASE}/admin/refunds/{requested.json()['id']}",
        headers=superuser_token_headers,
        json={"status": "succeeded"},
    )

    assert response.status_code == 409
    assert "额度已使用" in response.json()["detail"]


def test_wechat_callback_is_idempotent_and_rejects_wrong_amount(
    client: TestClient,
    db: Session,
    school_owner_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_code, _ = seed_catalog(db)
    order = create_order(client, school_owner_token_headers, plan_code)
    transaction = {
        "trade_state": "SUCCESS",
        "out_trade_no": order["order_no"],
        "transaction_id": f"wx-{uuid.uuid4()}",
        "success_time": datetime.now(UTC).isoformat(),
        "amount": {"total": order["amount_cents"]},
    }
    monkeypatch.setattr("app.services.wechat_pay.verify_notification", lambda **_: None)
    monkeypatch.setattr(
        "app.services.wechat_pay.decrypt_notification_resource",
        lambda _resource: transaction,
    )
    headers = {
        "Wechatpay-Timestamp": "1",
        "Wechatpay-Nonce": "nonce",
        "Wechatpay-Signature": "signature",
    }
    payload = {"id": f"event-{uuid.uuid4()}", "resource": {}}

    first = client.post(f"{BASE}/webhooks/wechat", headers=headers, json=payload)
    second = client.post(f"{BASE}/webhooks/wechat", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    grants = db.exec(
        select(AnswerQuotaGrant).where(
            AnswerQuotaGrant.order_id == uuid.UUID(order["id"])
        )
    ).all()
    assert len(grants) == 1

    wrong_order = create_order(client, school_owner_token_headers, plan_code)
    transaction.update(
        {
            "out_trade_no": wrong_order["order_no"],
            "transaction_id": f"wx-{uuid.uuid4()}",
            "amount": {"total": wrong_order["amount_cents"] + 1},
        }
    )
    bad = client.post(
        f"{BASE}/webhooks/wechat",
        headers=headers,
        json={"id": f"event-{uuid.uuid4()}", "resource": {}},
    )
    assert bad.status_code == 400
    assert "支付金额" in bad.json()["detail"]
