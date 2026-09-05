from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.cache import cache_set_nx
from app.db import get_db
from app.engines.entity_resolver import apply_entity_update, link
from app.engines.feature_store import recompute_features
from app.engines.state_engine import recompute_merchant_state
from app.ids import new_id, new_trace_id
from app.schemas.events import EventEnvelope


async def already_processed(event_id: str) -> bool:
    db = get_db()
    existing = await db.processed_events.find_one({"event_id": event_id})
    if existing:
        return True
    claimed = await cache_set_nx(f"evt:{event_id}", "1", ttl=7 * 86400)
    return not claimed


async def ingest_envelope(envelope: EventEnvelope, run_downstream: bool = True) -> dict[str, Any]:
    db = get_db()
    if await already_processed(envelope.event_id):
        return {"status": "duplicate", "event_id": envelope.event_id}

    doc = envelope.model_dump()
    doc["timestamp"] = envelope.timestamp
    doc["ingested_at"] = datetime.now(timezone.utc)
    try:
        await db.events.insert_one(doc)
        await db.processed_events.insert_one(
            {
                "event_id": envelope.event_id,
                "merchant_id": envelope.merchant_id,
                "processed_at": datetime.now(timezone.utc),
            }
        )
    except DuplicateKeyError:
        return {"status": "duplicate", "event_id": envelope.event_id}

    await apply_entity_update(envelope)
    if run_downstream:
        await recompute_features(envelope.merchant_id)
        await recompute_merchant_state(envelope.merchant_id)
    return {"status": "processed", "event_id": envelope.event_id}


async def ingest_raw(
    merchant_id: str,
    event_type: str,
    entity_id: str,
    payload: dict[str, Any],
    source: str = "api",
    timestamp: datetime | None = None,
    event_id: str | None = None,
    trace_id: str | None = None,
    run_downstream: bool = True,
) -> dict[str, Any]:
    envelope = EventEnvelope(
        event_id=event_id or new_id("evt"),
        event_type=event_type,
        merchant_id=merchant_id,
        entity_id=entity_id,
        timestamp=timestamp or datetime.now(timezone.utc),
        source=source,
        trace_id=trace_id or new_trace_id(),
        payload=payload,
    )
    return await ingest_envelope(envelope, run_downstream=run_downstream)


async def finalize_merchant(merchant_id: str) -> None:
    """Recompute derived layers after a bulk ingest that skipped per-event recompute."""
    from app.engines.feature_store import backfill_daily_series

    await backfill_daily_series(merchant_id)
    await recompute_features(merchant_id)
    await recompute_merchant_state(merchant_id)
