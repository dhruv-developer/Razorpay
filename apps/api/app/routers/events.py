from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.db import find_many
from app.engines.event_processor import ingest_raw
from app.schemas.events import EVENT_TYPES, IngestEventRequest
from app.security import authorized_merchant

router = APIRouter(prefix="/v1/events", tags=["events"])


@router.post("")
async def ingest_event(
    body: IngestEventRequest,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> dict[str, Any]:
    if body.event_type not in EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported event_type {body.event_type}")
    return await ingest_raw(
        principal["merchant_id"],
        body.event_type,
        body.entity_id,
        body.payload,
        source=body.source,
        timestamp=body.timestamp,
        event_id=body.event_id,
        trace_id=body.trace_id,
    )


@router.get("")
async def list_events(
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
    event_type: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    query: dict[str, Any] = {"merchant_id": principal["merchant_id"]}
    if event_type:
        query["event_type"] = event_type
    rows = await find_many("events", query, sort=[("timestamp", -1)], limit=min(limit, 500))
    return {"events": rows}
