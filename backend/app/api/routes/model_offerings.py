"""平台发布模型目录；学校只能看到公开名称，不能看到真实供应链。"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from app.api.deps import SessionDep, require_roles
from app.models import (
    ModelRoutePolicy,
    ModelRouteVersion,
    ModelRouteVersionStatus,
    OfferingRateVersion,
    OfferingRateVersionCreate,
    OfferingRateVersionPublic,
    OrganizationModelSelection,
    PlatformModelOffering,
    PlatformModelOfferingCreate,
    PlatformModelOfferingPublic,
    PlatformModelOfferingsPublic,
    PlatformModelOfferingUpdate,
    ProviderChannel,
    ProviderChannelStatus,
    ProviderInternalRateVersion,
    ProviderModelMapping,
    SchoolModelScope,
    User,
    UserRole,
)
from app.services import billing as billing_service
from app.services.model_purpose_policy import (
    REASONING_MODEL_PREFIXES,
    VISUAL_MODEL_PREFIXES,
)

router = APIRouter(prefix="/platform/model-offerings", tags=["model-offerings"])
PlatformSuperuser = Annotated[User, Depends(require_roles(UserRole.PLATFORM_SUPERUSER))]

_SCOPE_ROUTE_PURPOSES: dict[SchoolModelScope, dict[str, str]] = {
    SchoolModelScope.VISION: {
        "region_detection": "版面分析",
        "question_recognition": "题目识别",
        "score_structure_recognition": "分值结构识别",
        "answer_document_parsing": "答案文档识别",
        "rubric_question_recognition": "题目转录",
        "answer_recognition": "答题预览",
        "answer_extraction": "答题识别",
    },
    SchoolModelScope.REFERENCE_ANSWER: {
        "answer_preparation": "参考答案解题",
        "rubric_generation": "参考答案生成",
        "rubric_validation": "参考答案复核",
    },
    SchoolModelScope.GRADING: {
        "subjective_grading": "主观题判分",
    },
}


def _validate_target(
    session: SessionDep,
    canonical_model: str,
    scope: SchoolModelScope,
    *,
    require_enabled: bool,
) -> None:
    statement = (
        select(ProviderModelMapping)
        .join(ProviderChannel, ProviderModelMapping.channel_id == ProviderChannel.id)
        .where(
            ProviderModelMapping.canonical_model == canonical_model,
        )
    )
    if require_enabled:
        statement = statement.where(
            ProviderChannel.status == ProviderChannelStatus.ACTIVE,
            ProviderModelMapping.enabled.is_(True),
            ProviderModelMapping.usage_metering_verified.is_(True),
        )
    mapping = session.exec(statement).first()
    if not mapping:
        raise HTTPException(
            status_code=422,
            detail=(
                "发布前请先启用对应中转渠道和标准模型映射"
                if require_enabled
                else "请先在对应中转渠道添加该标准模型映射"
            ),
        )
    if not mapping.supports_structured_output:
        raise HTTPException(
            status_code=422,
            detail="点凡阅卷的处理方案必须使用支持结构化输出的模型",
        )
    model = canonical_model.casefold()
    if scope == SchoolModelScope.VISION and not model.startswith(VISUAL_MODEL_PREFIXES):
        raise HTTPException(
            status_code=422,
            detail="卷面识别方案只允许使用 Gemini 3.7/3.6/3.5 Flash",
        )
    if scope != SchoolModelScope.VISION and not model.startswith(
        REASONING_MODEL_PREFIXES
    ):
        raise HTTPException(
            status_code=422,
            detail="参考答案和建议评分方案只允许使用 GPT-5.6 Sol、GPT-5.6 Terra 或 Kimi",
        )
    if (
        scope in {SchoolModelScope.VISION, SchoolModelScope.REFERENCE_ANSWER}
        and not mapping.supports_vision
    ):
        raise HTTPException(
            status_code=422,
            detail="卷面识别和参考答案方案必须使用支持图片输入的模型",
        )
    if require_enabled:
        published_purposes = set(
            session.exec(
                select(ModelRoutePolicy.purpose)
                .join(
                    ModelRouteVersion,
                    ModelRouteVersion.policy_id == ModelRoutePolicy.id,
                )
                .where(
                    ModelRoutePolicy.canonical_model == canonical_model,
                    ModelRoutePolicy.enabled.is_(True),
                    ModelRouteVersion.status == ModelRouteVersionStatus.PUBLISHED,
                )
            ).all()
        )
        required = _SCOPE_ROUTE_PURPOSES[scope]
        missing = [
            label
            for purpose, label in required.items()
            if purpose not in published_purposes
        ]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"发布前还需为以下功能发布该模型路由：{'、'.join(missing)}",
            )


def _public(
    session: SessionDep, item: PlatformModelOffering
) -> PlatformModelOfferingPublic:
    mapped_channel_count = session.exec(
        select(func.count(func.distinct(ProviderModelMapping.channel_id)))
        .join(ProviderChannel, ProviderModelMapping.channel_id == ProviderChannel.id)
        .where(
            ProviderModelMapping.canonical_model == item.canonical_model,
            ProviderModelMapping.enabled.is_(True),
            ProviderChannel.status == ProviderChannelStatus.ACTIVE,
        )
    ).one()
    purposes = list(
        session.exec(
            select(ModelRoutePolicy.purpose).where(
                ModelRoutePolicy.canonical_model == item.canonical_model,
                ModelRoutePolicy.enabled.is_(True),
            )
        ).all()
    )
    return PlatformModelOfferingPublic(
        **item.model_dump(),
        mapped_channel_count=mapped_channel_count,
        route_purposes=purposes,
    )


def _rate_public(
    session: SessionDep, rate: OfferingRateVersion
) -> OfferingRateVersionPublic:
    offering = session.get(PlatformModelOffering, rate.offering_id)
    worst_cost = 0
    if offering:
        costs = session.exec(
            select(ProviderInternalRateVersion).where(
                ProviderInternalRateVersion.canonical_model == offering.canonical_model,
                ProviderInternalRateVersion.effective_at <= datetime.now(UTC),
            )
        ).all()
        for cost in costs:
            worst_cost = max(
                worst_cost,
                cost.input_micrormb_per_million,
                cost.output_micrormb_per_million,
                cost.image_micrormb_per_million,
            )
    prices = [
        value
        for value in (
            rate.input_microcredits_per_million,
            rate.output_microcredits_per_million,
            rate.image_microcredits_per_million,
        )
        if value > 0
    ]
    lowest_price = min(prices) if prices else 0
    margin_valid = not worst_cost or (
        lowest_price > 0
        and (lowest_price - worst_cost) * 10_000
        >= lowest_price * rate.minimum_margin_bps
    )
    return OfferingRateVersionPublic(
        id=rate.id,
        offering_id=rate.offering_id,
        version=rate.version,
        effective_at=rate.effective_at,
        input_credits_per_million=billing_service.microcredits_to_credits(
            rate.input_microcredits_per_million
        ),
        output_credits_per_million=billing_service.microcredits_to_credits(
            rate.output_microcredits_per_million
        ),
        image_credits_per_million=billing_service.microcredits_to_credits(
            rate.image_microcredits_per_million
        ),
        target_margin_percent=rate.target_margin_bps / 100,
        minimum_margin_percent=rate.minimum_margin_bps / 100,
        margin_valid=margin_valid,
        created_at=rate.created_at,
    )


@router.get("", response_model=PlatformModelOfferingsPublic)
def list_model_offerings(session: SessionDep, _current_user: PlatformSuperuser) -> Any:
    items = list(
        session.exec(
            select(PlatformModelOffering).order_by(
                col(PlatformModelOffering.scope),
                PlatformModelOffering.sort_order,
                PlatformModelOffering.display_name,
            )
        ).all()
    )
    return PlatformModelOfferingsPublic(
        data=[_public(session, item) for item in items], count=len(items)
    )


@router.post("", response_model=PlatformModelOfferingPublic)
def create_model_offering(
    session: SessionDep,
    _current_user: PlatformSuperuser,
    offering_in: PlatformModelOfferingCreate,
) -> Any:
    _validate_target(
        session,
        offering_in.canonical_model,
        offering_in.scope,
        require_enabled=offering_in.published,
    )
    item = PlatformModelOffering(**offering_in.model_dump())
    session.add(item)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="公开模型代码已存在") from exc
    session.refresh(item)
    return _public(session, item)


@router.patch("/{offering_id}", response_model=PlatformModelOfferingPublic)
def update_model_offering(
    session: SessionDep,
    _current_user: PlatformSuperuser,
    offering_id: uuid.UUID,
    offering_in: PlatformModelOfferingUpdate,
) -> Any:
    item = session.get(PlatformModelOffering, offering_id)
    if not item:
        raise HTTPException(status_code=404, detail="公开模型不存在")
    updates = offering_in.model_dump(exclude_unset=True)
    canonical_model = str(updates.get("canonical_model", item.canonical_model))
    scope = updates.get("scope", item.scope)
    published = bool(updates.get("published", item.published))
    _validate_target(
        session,
        canonical_model,
        scope,
        require_enabled=published,
    )
    if scope != item.scope:
        in_use = session.exec(
            select(func.count())
            .select_from(OrganizationModelSelection)
            .where(OrganizationModelSelection.offering_id == item.id)
        ).one()
        if in_use:
            raise HTTPException(
                status_code=409,
                detail="该方案已被学校使用，不能直接修改用途；请新建方案后再切换",
            )
    item.sqlmodel_update(updates)
    item.updated_at = datetime.now(UTC)
    session.add(item)
    session.commit()
    session.refresh(item)
    return _public(session, item)


@router.get("/{offering_id}/rates", response_model=list[OfferingRateVersionPublic])
def list_offering_rates(
    session: SessionDep,
    _current_user: PlatformSuperuser,
    offering_id: uuid.UUID,
) -> Any:
    if not session.get(PlatformModelOffering, offering_id):
        raise HTTPException(status_code=404, detail="学校方案不存在")
    rates = session.exec(
        select(OfferingRateVersion)
        .where(OfferingRateVersion.offering_id == offering_id)
        .order_by(col(OfferingRateVersion.effective_at).desc())
    ).all()
    return [_rate_public(session, rate) for rate in rates]


@router.post("/{offering_id}/rates", response_model=OfferingRateVersionPublic)
def create_offering_rate(
    session: SessionDep,
    current_user: PlatformSuperuser,
    offering_id: uuid.UUID,
    rate_in: OfferingRateVersionCreate,
) -> Any:
    if not session.get(PlatformModelOffering, offering_id):
        raise HTTPException(status_code=404, detail="学校方案不存在")
    rate = OfferingRateVersion(
        offering_id=offering_id,
        version=rate_in.version,
        effective_at=rate_in.effective_at,
        input_microcredits_per_million=billing_service.credits_to_microcredits(
            rate_in.input_credits_per_million
        ),
        output_microcredits_per_million=billing_service.credits_to_microcredits(
            rate_in.output_credits_per_million
        ),
        image_microcredits_per_million=billing_service.credits_to_microcredits(
            rate_in.image_credits_per_million
        ),
        target_margin_bps=round(rate_in.target_margin_percent * 100),
        minimum_margin_bps=round(rate_in.minimum_margin_percent * 100),
        created_by_id=current_user.id,
    )
    session.add(rate)
    try:
        session.flush()
        if not _rate_public(session, rate).margin_valid:
            session.rollback()
            raise HTTPException(
                status_code=422,
                detail="该费率低于最低毛利保护线，不能发布",
            )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="方案费率版本已存在") from exc
    session.refresh(rate)
    return _rate_public(session, rate)
