"""点凡公开模型目录：学校只看产品名，真实渠道与上游模型留在平台侧。"""

import uuid

from sqlmodel import Session, col, select

from app.models import (
    OrganizationModelSelection,
    PlatformModelOffering,
    SchoolModelOptionPublic,
    SchoolModelScope,
    SchoolModelScopePublic,
    SchoolModelSettingsPublic,
)


def school_model_settings(
    session: Session, org_id: uuid.UUID
) -> SchoolModelSettingsPublic:
    offerings = list(
        session.exec(
            select(PlatformModelOffering)
            .where(
                PlatformModelOffering.published.is_(True),
                PlatformModelOffering.school_selectable.is_(True),
            )
            .order_by(
                col(PlatformModelOffering.scope),
                PlatformModelOffering.sort_order,
                PlatformModelOffering.display_name,
            )
        ).all()
    )
    selected = {
        row.scope: row.offering_id
        for row in session.exec(
            select(OrganizationModelSelection).where(
                OrganizationModelSelection.org_id == org_id
            )
        ).all()
    }
    return SchoolModelSettingsPublic(
        scopes=[
            SchoolModelScopePublic(
                scope=scope,
                selected_option_id=selected.get(scope),
                options=[
                    SchoolModelOptionPublic(
                        id=item.id,
                        code=item.code,
                        display_name=item.display_name,
                        description=item.description,
                        scope=item.scope,
                    )
                    for item in offerings
                    if item.scope == scope
                ],
            )
            for scope in SchoolModelScope
        ]
    )
