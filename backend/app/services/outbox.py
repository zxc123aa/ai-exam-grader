from __future__ import annotations

import logging

from sqlmodel import Session, col, select

from app.models import OutboxEvent, get_datetime_utc

logger = logging.getLogger(__name__)


def dispatch_pending_events(session: Session, *, limit: int = 100) -> int:
    """Claim and dispatch committed domain events.

    Email/ERP integrations can be added per event type without coupling them to
    payment transactions. Unknown events are acknowledged after being logged.
    """
    events = session.exec(
        select(OutboxEvent)
        .where(
            col(OutboxEvent.processed_at).is_(None),
            OutboxEvent.available_at <= get_datetime_utc(),
        )
        .order_by(OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for event in events:
        event.attempts += 1
        logger.info(
            "outbox event dispatched",
            extra={
                "event_type": event.event_type,
                "aggregate_id": event.aggregate_id,
            },
        )
        event.processed_at = get_datetime_utc()
        event.last_error = None
        session.add(event)
    return len(events)
