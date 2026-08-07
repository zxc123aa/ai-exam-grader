from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import text
from sqlmodel import col, select

from app.api.deps import SessionDep, require_roles
from app.models import (
    AddonSku,
    AddonSkuCreate,
    AdminCommerceOrderPublic,
    BankTransferConfirm,
    BillingSummaryPublic,
    CatalogItemPublic,
    CatalogPublicationUpdate,
    CommerceCatalogPublic,
    CommerceOrder,
    CommerceOrderCreate,
    CommerceOrderPublic,
    InvoiceApplication,
    InvoiceApplicationCreate,
    InvoiceApplicationPublic,
    InvoiceReview,
    Organization,
    PaymentAttempt,
    PaymentMethod,
    PaymentStatus,
    PaymentWebhookEvent,
    PlanVersion,
    PlanVersionCreate,
    RefundRequest,
    RefundRequestCreate,
    RefundRequestPublic,
    RefundReview,
    RefundStatus,
    User,
    UserRole,
    get_datetime_utc,
)
from app.services import billing as billing_service
from app.services import commerce as commerce_service
from app.services import wechat_pay

router = APIRouter(prefix="/commerce", tags=["commerce"])

SchoolBuyer = Annotated[
    User, Depends(require_roles(UserRole.SCHOOL_OWNER, UserRole.SCHOOL_ADMIN))
]
PlatformFinance = Annotated[
    User,
    Depends(require_roles(UserRole.PLATFORM_SUPERUSER, UserRole.PLATFORM_ADMIN)),
]


@router.get("/catalog", response_model=CommerceCatalogPublic)
def catalog(session: SessionDep) -> CommerceCatalogPublic:
    plans = session.exec(
        select(PlanVersion)
        .where(PlanVersion.published.is_(True))
        .order_by(PlanVersion.annual_price_cents)
    ).all()
    addons = session.exec(
        select(AddonSku)
        .where(AddonSku.published.is_(True))
        .order_by(AddonSku.price_cents)
    ).all()
    return CommerceCatalogPublic(
        data=[
            CatalogItemPublic(
                item_type="plan",
                code=item.code,
                display_name=item.display_name,
                description=item.description,
                price_cents=item.annual_price_cents,
                answer_quota=item.included_answers,
                validity_days=item.validity_days,
            )
            for item in plans
        ]
        + [
            CatalogItemPublic(
                item_type="addon",
                code=item.code,
                display_name=item.display_name,
                description=item.description,
                price_cents=item.price_cents,
                answer_quota=item.answer_quota,
                validity_days=item.validity_days,
            )
            for item in addons
        ]
    )


@router.post("/admin/plans", response_model=PlanVersion)
def create_plan(
    session: SessionDep, _current_user: PlatformFinance, plan_in: PlanVersionCreate
) -> PlanVersion:
    existing = session.exec(
        select(PlanVersion).where(
            PlanVersion.code == plan_in.code, PlanVersion.version == plan_in.version
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="套餐版本已存在")
    plan = PlanVersion(**plan_in.model_dump())
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


@router.post("/admin/addons", response_model=AddonSku)
def create_addon(
    session: SessionDep, _current_user: PlatformFinance, addon_in: AddonSkuCreate
) -> AddonSku:
    existing = session.exec(
        select(AddonSku).where(AddonSku.code == addon_in.code)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="加量包编码已存在")
    addon = AddonSku(**addon_in.model_dump())
    session.add(addon)
    session.commit()
    session.refresh(addon)
    return addon


@router.get("/admin/plans", response_model=list[PlanVersion])
def list_plans(
    session: SessionDep, _current_user: PlatformFinance
) -> list[PlanVersion]:
    return list(
        session.exec(
            select(PlanVersion).order_by(
                col(PlanVersion.created_at).desc(),
                col(PlanVersion.version).desc(),
            )
        ).all()
    )


@router.patch("/admin/plans/{plan_id}/publication", response_model=PlanVersion)
def update_plan_publication(
    session: SessionDep,
    _current_user: PlatformFinance,
    plan_id: uuid.UUID,
    update: CatalogPublicationUpdate,
) -> PlanVersion:
    plan = session.get(PlanVersion, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="套餐版本不存在")
    plan.published = update.published
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


@router.get("/admin/addons", response_model=list[AddonSku])
def list_addons(
    session: SessionDep, _current_user: PlatformFinance
) -> list[AddonSku]:
    return list(
        session.exec(
            select(AddonSku).order_by(col(AddonSku.created_at).desc())
        ).all()
    )


@router.patch("/admin/addons/{addon_id}/publication", response_model=AddonSku)
def update_addon_publication(
    session: SessionDep,
    _current_user: PlatformFinance,
    addon_id: uuid.UUID,
    update: CatalogPublicationUpdate,
) -> AddonSku:
    addon = session.get(AddonSku, addon_id)
    if not addon:
        raise HTTPException(status_code=404, detail="加量包不存在")
    addon.published = update.published
    session.add(addon)
    session.commit()
    session.refresh(addon)
    return addon


@router.get("/admin/orders", response_model=list[AdminCommerceOrderPublic])
def list_orders(
    session: SessionDep, _current_user: PlatformFinance
) -> list[AdminCommerceOrderPublic]:
    rows = session.exec(
        select(CommerceOrder, Organization)
        .join(Organization, Organization.id == CommerceOrder.org_id)
        .order_by(col(CommerceOrder.created_at).desc())
    ).all()
    return [
        AdminCommerceOrderPublic(
            **commerce_service.order_public(session, order).model_dump(),
            org_name=org.name,
        )
        for order, org in rows
    ]


@router.post("/orders", response_model=CommerceOrderPublic)
def create_order(
    session: SessionDep, current_user: SchoolBuyer, order_in: CommerceOrderCreate
) -> CommerceOrderPublic:
    order = commerce_service.create_order(
        session, current_user=current_user, order_in=order_in
    )
    return commerce_service.order_public(session, order)


def _get_order_for_user(
    session: SessionDep, current_user: User, order_id: uuid.UUID
) -> CommerceOrder:
    order = session.get(CommerceOrder, order_id)
    if not order or current_user.org_id != order.org_id:
        raise HTTPException(status_code=404, detail="订单不存在")
    return order


@router.get("/orders/{order_id}", response_model=CommerceOrderPublic)
def read_order(
    session: SessionDep, current_user: SchoolBuyer, order_id: uuid.UUID
) -> CommerceOrderPublic:
    return commerce_service.order_public(
        session, _get_order_for_user(session, current_user, order_id)
    )


@router.post("/orders/{order_id}/wechat-pay")
def start_wechat_pay(
    session: SessionDep, current_user: SchoolBuyer, order_id: uuid.UUID
) -> dict[str, str]:
    order = _get_order_for_user(session, current_user, order_id)
    existing = session.exec(
        select(PaymentAttempt)
        .where(
            PaymentAttempt.order_id == order.id,
            PaymentAttempt.method == PaymentMethod.WECHAT_NATIVE,
            PaymentAttempt.status == PaymentStatus.PENDING,
        )
        .order_by(col(PaymentAttempt.created_at).desc())
    ).first()
    if existing and existing.code_url:
        return {"code_url": existing.code_url}
    try:
        result = wechat_pay.create_native_payment(
            order_no=order.order_no,
            description="点凡阅卷服务",
            amount_cents=order.amount_cents,
        )
    except wechat_pay.WeChatPayError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    attempt = PaymentAttempt(
        order_id=order.id,
        method=PaymentMethod.WECHAT_NATIVE,
        amount_cents=order.amount_cents,
        code_url=result["code_url"],
        raw_response=result,
    )
    session.add(attempt)
    session.commit()
    return {"code_url": result["code_url"]}


@router.post("/orders/{order_id}/bank-transfer", response_model=CommerceOrderPublic)
def confirm_bank_transfer(
    session: SessionDep,
    _current_user: PlatformFinance,
    order_id: uuid.UUID,
    transfer: BankTransferConfirm,
) -> CommerceOrderPublic:
    order = commerce_service.record_payment_and_fulfill(
        session,
        order_id=order_id,
        method=PaymentMethod.BANK_TRANSFER,
        provider_transaction_id=transfer.transaction_reference,
        paid_at=transfer.paid_at,
    )
    return commerce_service.order_public(session, order)


@router.post("/invoices", response_model=InvoiceApplicationPublic)
def apply_invoice(
    session: SessionDep,
    current_user: SchoolBuyer,
    invoice_in: InvoiceApplicationCreate,
) -> InvoiceApplication:
    order = _get_order_for_user(session, current_user, invoice_in.order_id)
    session.exec(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))").bindparams(
            key=f"commerce-invoice:{order.id}"
        )
    )
    if order.fulfilled_at is None:
        raise HTTPException(status_code=409, detail="订单完成后才能申请发票")
    existing = session.exec(
        select(InvoiceApplication).where(InvoiceApplication.order_id == order.id)
    ).first()
    if existing:
        return existing
    application = InvoiceApplication(
        order_id=order.id,
        org_id=order.org_id,
        title=invoice_in.title,
        tax_number=invoice_in.tax_number,
        email=str(invoice_in.email),
        amount_cents=order.amount_cents,
        created_by_id=current_user.id,
    )
    session.add(application)
    session.commit()
    session.refresh(application)
    return application


@router.get("/admin/invoices", response_model=list[InvoiceApplicationPublic])
def list_invoices(
    session: SessionDep, _current_user: PlatformFinance
) -> list[InvoiceApplication]:
    return list(
        session.exec(
            select(InvoiceApplication).order_by(
                col(InvoiceApplication.created_at).desc()
            )
        ).all()
    )


@router.patch("/admin/invoices/{application_id}", response_model=InvoiceApplicationPublic)
def review_invoice(
    session: SessionDep,
    _current_user: PlatformFinance,
    application_id: uuid.UUID,
    review: InvoiceReview,
) -> InvoiceApplication:
    application = session.get(InvoiceApplication, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="发票申请不存在")
    if review.status == "issued" and not review.invoice_no:
        raise HTTPException(status_code=422, detail="开票后必须填写发票号码")
    if review.status == "rejected" and not review.reject_reason:
        raise HTTPException(status_code=422, detail="驳回时必须填写原因")
    application.status = review.status
    application.invoice_no = review.invoice_no
    application.reject_reason = review.reject_reason
    application.updated_at = get_datetime_utc()
    session.add(application)
    session.commit()
    session.refresh(application)
    return application


@router.post("/refunds", response_model=RefundRequestPublic)
def request_refund(
    session: SessionDep,
    current_user: SchoolBuyer,
    refund_in: RefundRequestCreate,
) -> RefundRequest:
    order = _get_order_for_user(session, current_user, refund_in.order_id)
    session.exec(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))").bindparams(
            key=f"commerce-refund:{order.id}"
        )
    )
    if order.fulfilled_at is None:
        raise HTTPException(status_code=409, detail="未完成订单无需退款，请直接关闭订单")
    if refund_in.amount_cents > order.amount_cents:
        raise HTTPException(status_code=422, detail="退款金额不能超过订单金额")
    if refund_in.amount_cents != order.amount_cents:
        raise HTTPException(status_code=422, detail="当前仅支持整单退款")
    existing = session.exec(
        select(RefundRequest).where(RefundRequest.order_id == order.id)
    ).first()
    if existing:
        return existing
    refund = RefundRequest(
        order_id=order.id,
        org_id=order.org_id,
        amount_cents=refund_in.amount_cents,
        reason=refund_in.reason,
        requested_by_id=current_user.id,
    )
    session.add(refund)
    session.commit()
    session.refresh(refund)
    return refund


@router.get("/admin/refunds", response_model=list[RefundRequestPublic])
def list_refunds(
    session: SessionDep, _current_user: PlatformFinance
) -> list[RefundRequest]:
    return list(
        session.exec(
            select(RefundRequest).order_by(col(RefundRequest.created_at).desc())
        ).all()
    )


@router.patch("/admin/refunds/{refund_id}", response_model=RefundRequestPublic)
def review_refund(
    session: SessionDep,
    current_user: PlatformFinance,
    refund_id: uuid.UUID,
    review: RefundReview,
) -> RefundRequest:
    refund = session.get(RefundRequest, refund_id)
    if not refund:
        raise HTTPException(status_code=404, detail="退款申请不存在")
    if review.status == "succeeded":
        return commerce_service.finalize_refund(
            session, refund_id=refund.id, reviewed_by_id=current_user.id
        )
    refund.status = RefundStatus(review.status)
    refund.reviewed_by_id = current_user.id
    refund.review_note = review.review_note
    refund.updated_at = get_datetime_utc()
    session.add(refund)
    session.commit()
    session.refresh(refund)
    return refund


@router.get("/org/billing", response_model=BillingSummaryPublic)
def org_billing(
    session: SessionDep, current_user: SchoolBuyer
) -> BillingSummaryPublic:
    assert current_user.org_id is not None
    return billing_service.billing_summary(session, current_user.org_id)


@router.post("/webhooks/wechat")
async def wechat_webhook(
    request: Request,
    session: SessionDep,
    wechatpay_timestamp: str = Header(alias="Wechatpay-Timestamp"),
    wechatpay_nonce: str = Header(alias="Wechatpay-Nonce"),
    wechatpay_signature: str = Header(alias="Wechatpay-Signature"),
) -> dict[str, str]:
    body = await request.body()
    try:
        wechat_pay.verify_notification(
            timestamp=wechatpay_timestamp,
            nonce=wechatpay_nonce,
            signature=wechatpay_signature,
            body=body,
        )
        payload = await request.json()
        event_id = str(payload["id"])
        existing = session.exec(
            select(PaymentWebhookEvent).where(
                PaymentWebhookEvent.event_id == event_id
            )
        ).first()
        if existing and existing.processed_at:
            return {"code": "SUCCESS", "message": "成功"}
        event = existing or PaymentWebhookEvent(
            event_id=event_id,
            event_type=str(payload.get("event_type", "TRANSACTION.SUCCESS")),
            signature_verified=True,
            payload=payload,
        )
        session.add(event)
        transaction = wechat_pay.decrypt_notification_resource(payload["resource"])
        if transaction.get("trade_state") != "SUCCESS":
            event.processed_at = get_datetime_utc()
            session.commit()
            return {"code": "SUCCESS", "message": "成功"}
        order = session.exec(
            select(CommerceOrder).where(
                CommerceOrder.order_no == transaction["out_trade_no"]
            )
        ).first()
        if not order:
            raise wechat_pay.WeChatPayError("回调订单不存在")
        amount = int(transaction.get("amount", {}).get("total", -1))
        if amount != order.amount_cents:
            raise wechat_pay.WeChatPayError("支付金额与订单不一致")
        paid_at = datetime.fromisoformat(transaction["success_time"])
        commerce_service.record_payment_and_fulfill(
            session,
            order_id=order.id,
            method=PaymentMethod.WECHAT_NATIVE,
            provider_transaction_id=transaction["transaction_id"],
            paid_at=paid_at,
            raw_response=transaction,
        )
        event.processed_at = get_datetime_utc()
        session.add(event)
        session.commit()
    except (KeyError, ValueError, wechat_pay.WeChatPayError) as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": "SUCCESS", "message": "成功"}
