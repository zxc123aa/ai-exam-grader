from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, col, select

from app.models import (
    AddonSku,
    AnswerQuotaGrant,
    CommerceOrder,
    CommerceOrderCreate,
    CommerceOrderItemPublic,
    CommerceOrderLineCreate,
    CommerceOrderPublic,
    CommerceOrderStatus,
    CreditGrantSource,
    OrderItem,
    OrganizationSubscription,
    OutboxEvent,
    PaymentAttempt,
    PaymentMethod,
    PaymentStatus,
    PlanVersion,
    RefundRequest,
    RefundStatus,
    SubscriptionStatus,
    User,
    get_datetime_utc,
)
from app.services.billing import entitlement, grant_answer_quota


def _order_no() -> str:
    return f"DF{datetime.now(UTC):%Y%m%d%H%M%S}{secrets.token_hex(4).upper()}"


def _resolve_line(session: Session, line: CommerceOrderLineCreate) -> dict:
    if line.item_type == "plan":
        item = session.exec(
            select(PlanVersion)
            .where(PlanVersion.code == line.code, PlanVersion.published.is_(True))
            .order_by(col(PlanVersion.version).desc())
        ).first()
        if not item:
            raise HTTPException(status_code=422, detail=f"套餐 {line.code} 不可购买")
        return {
            "item_type": "plan",
            "sku_code": item.code,
            "display_name": item.display_name,
            "quantity": line.quantity,
            "unit_price_cents": item.annual_price_cents,
            "answer_quota": item.included_answers,
            "validity_days": item.validity_days,
            "metadata_json": {"plan_version_id": str(item.id), "version": item.version},
        }
    item = session.exec(
        select(AddonSku).where(AddonSku.code == line.code, AddonSku.published.is_(True))
    ).first()
    if not item:
        raise HTTPException(status_code=422, detail=f"加量包 {line.code} 不可购买")
    return {
        "item_type": "addon",
        "sku_code": item.code,
        "display_name": item.display_name,
        "quantity": line.quantity,
        "unit_price_cents": item.price_cents,
        "answer_quota": item.answer_quota,
        "validity_days": item.validity_days,
        "metadata_json": {"addon_sku_id": str(item.id)},
    }


def create_order(
    session: Session, *, current_user: User, order_in: CommerceOrderCreate
) -> CommerceOrder:
    if current_user.org_id is None:
        raise HTTPException(status_code=403, detail="平台账号不能创建学校订单")
    existing = session.exec(
        select(CommerceOrder).where(
            CommerceOrder.idempotency_key == order_in.idempotency_key
        )
    ).first()
    if existing:
        if existing.org_id != current_user.org_id:
            raise HTTPException(status_code=409, detail="幂等键冲突")
        return existing
    lines = [_resolve_line(session, line) for line in order_in.items]
    plan_count = sum(line["quantity"] for line in lines if line["item_type"] == "plan")
    if plan_count > 1:
        raise HTTPException(status_code=422, detail="一张订单最多购买一个年度套餐")
    if plan_count == 0 and entitlement(session, current_user.org_id) in {
        "not_configured",
        "expired",
    }:
        raise HTTPException(status_code=409, detail="请先购买或续费年度服务套餐")
    amount = sum(line["quantity"] * line["unit_price_cents"] for line in lines)
    order = CommerceOrder(
        order_no=_order_no(),
        org_id=current_user.org_id,
        amount_cents=amount,
        idempotency_key=order_in.idempotency_key,
        created_by_id=current_user.id,
    )
    session.add(order)
    session.flush()
    for line in lines:
        session.add(OrderItem(order_id=order.id, **line))
    session.commit()
    session.refresh(order)
    return order


def order_public(session: Session, order: CommerceOrder) -> CommerceOrderPublic:
    items = session.exec(
        select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)
    ).all()
    return CommerceOrderPublic(
        id=order.id,
        order_no=order.order_no,
        org_id=order.org_id,
        status=order.status,
        amount_cents=order.amount_cents,
        currency=order.currency,
        items=[CommerceOrderItemPublic.model_validate(item) for item in items],
        created_at=order.created_at,
        paid_at=order.paid_at,
        fulfilled_at=order.fulfilled_at,
    )


def record_payment_and_fulfill(
    session: Session,
    *,
    order_id: uuid.UUID,
    method: PaymentMethod,
    provider_transaction_id: str,
    paid_at: datetime | None = None,
    raw_response: dict | None = None,
) -> CommerceOrder:
    session.exec(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))").bindparams(
            key=f"commerce-order:{order_id}"
        )
    )
    order = session.exec(
        select(CommerceOrder).where(CommerceOrder.id == order_id).with_for_update()
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    duplicate = session.exec(
        select(PaymentAttempt).where(
            PaymentAttempt.provider_transaction_id == provider_transaction_id
        )
    ).first()
    if duplicate and duplicate.order_id != order.id:
        raise HTTPException(status_code=409, detail="支付流水已关联其他订单")
    if order.status in {CommerceOrderStatus.FULFILLED, CommerceOrderStatus.REFUNDED}:
        return order
    paid_time = paid_at or get_datetime_utc()
    if not duplicate:
        session.add(
            PaymentAttempt(
                order_id=order.id,
                method=method,
                status=PaymentStatus.SUCCEEDED,
                provider_transaction_id=provider_transaction_id,
                amount_cents=order.amount_cents,
                raw_response=raw_response or {},
                succeeded_at=paid_time,
            )
        )
    order.status = CommerceOrderStatus.PAID
    order.paid_at = paid_time
    session.add(order)
    _fulfill_order(session, order)
    session.commit()
    session.refresh(order)
    return order


def _fulfill_order(session: Session, order: CommerceOrder) -> None:
    if order.fulfilled_at is not None:
        return
    items = session.exec(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    items.sort(key=lambda item: 0 if item.item_type == "plan" else 1)
    for item in items:
        answers = item.answer_quota * item.quantity
        if item.item_type == "plan":
            paid_time = order.paid_at or get_datetime_utc()
            active_subscriptions = session.exec(
                select(OrganizationSubscription)
                .where(
                    OrganizationSubscription.org_id == order.org_id,
                    OrganizationSubscription.status == SubscriptionStatus.ACTIVE,
                )
                .with_for_update()
            ).all()
            latest_end = max(
                (row.ends_at for row in active_subscriptions), default=paid_time
            )
            starts_at = paid_time
            ends_at = max(paid_time, latest_end) + timedelta(days=item.validity_days)
            rate_version_id = _default_rate_version_id(session)
            for active in active_subscriptions:
                active.status = SubscriptionStatus.EXPIRED
                active.updated_at = get_datetime_utc()
                session.add(active)
            item.metadata_json = {
                **item.metadata_json,
                "previous_active_subscription_ids": [
                    str(row.id) for row in active_subscriptions
                ],
            }
            session.add(item)
            subscription = OrganizationSubscription(
                org_id=order.org_id,
                contract_no=f"ORDER-{order.order_no}",
                plan_code=item.sku_code,
                status=SubscriptionStatus.ACTIVE,
                starts_at=starts_at,
                ends_at=ends_at,
                rate_version_id=rate_version_id,
            )
            session.add(subscription)
            session.flush()
        if answers:
            grant_answer_quota(
                session,
                org_id=order.org_id,
                answers=answers,
                source=CreditGrantSource.SUBSCRIPTION
                if item.item_type == "plan"
                else CreditGrantSource.TOP_UP,
                actor_id=None,
                note=f"订单 {order.order_no} 自动履约",
                order_id=order.id,
            )
    order.status = CommerceOrderStatus.FULFILLED
    order.fulfilled_at = get_datetime_utc()
    order.updated_at = get_datetime_utc()
    session.add(order)
    session.add(
        OutboxEvent(
            event_type="commerce.order.fulfilled",
            aggregate_type="commerce_order",
            aggregate_id=str(order.id),
            idempotency_key=f"commerce-order-fulfilled:{order.id}",
            payload={"order_no": order.order_no, "org_id": str(order.org_id)},
        )
    )


def _default_rate_version_id(session: Session) -> uuid.UUID:
    from app.models import BillingRateVersion

    rate = session.exec(
        select(BillingRateVersion).order_by(col(BillingRateVersion.effective_at).desc())
    ).first()
    if not rate:
        raise HTTPException(status_code=409, detail="平台尚未配置计量费率")
    return rate.id


def finalize_refund(
    session: Session, *, refund_id: uuid.UUID, reviewed_by_id: uuid.UUID
) -> RefundRequest:
    refund = session.exec(
        select(RefundRequest).where(RefundRequest.id == refund_id).with_for_update()
    ).first()
    if not refund:
        raise HTTPException(status_code=404, detail="退款申请不存在")
    order = session.exec(
        select(CommerceOrder)
        .where(CommerceOrder.id == refund.order_id)
        .with_for_update()
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if (
        refund.status == RefundStatus.SUCCEEDED
        and order.status == CommerceOrderStatus.REFUNDED
    ):
        return refund
    if refund.amount_cents != order.amount_cents:
        raise HTTPException(status_code=409, detail="当前仅支持整单退款")
    grants = session.exec(
        select(AnswerQuotaGrant)
        .where(AnswerQuotaGrant.order_id == order.id)
        .with_for_update()
    ).all()
    if any(grant.reserved_answers or grant.consumed_answers for grant in grants):
        raise HTTPException(status_code=409, detail="订单额度已使用，不能自动退款")
    for grant in grants:
        session.delete(grant)
    subscription = session.exec(
        select(OrganizationSubscription).where(
            OrganizationSubscription.contract_no == f"ORDER-{order.order_no}"
        )
    ).first()
    if subscription:
        subscription.status = SubscriptionStatus.EXPIRED
        subscription.updated_at = get_datetime_utc()
        session.add(subscription)
        plan_item = session.exec(
            select(OrderItem).where(
                OrderItem.order_id == order.id,
                OrderItem.item_type == "plan",
            )
        ).first()
        previous_ids = (
            plan_item.metadata_json.get("previous_active_subscription_ids", [])
            if plan_item
            else []
        )
        now = get_datetime_utc()
        for previous_id in previous_ids:
            try:
                previous = session.get(OrganizationSubscription, uuid.UUID(previous_id))
            except (TypeError, ValueError):
                continue
            if previous and previous.ends_at > now:
                previous.status = SubscriptionStatus.ACTIVE
                previous.updated_at = now
                session.add(previous)
    order.status = CommerceOrderStatus.REFUNDED
    order.updated_at = get_datetime_utc()
    refund.status = RefundStatus.SUCCEEDED
    refund.reviewed_by_id = reviewed_by_id
    refund.updated_at = get_datetime_utc()
    session.add(order)
    session.add(refund)
    session.add(
        OutboxEvent(
            event_type="commerce.refund.succeeded",
            aggregate_type="refund_request",
            aggregate_id=str(refund.id),
            idempotency_key=f"commerce-refund-succeeded:{refund.id}",
            payload={"order_no": order.order_no, "amount_cents": refund.amount_cents},
        )
    )
    session.commit()
    session.refresh(refund)
    return refund
