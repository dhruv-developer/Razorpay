from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db import aggregate, get_db


async def sum_field(
    collection: str,
    merchant_id: str,
    match: dict[str, Any],
    field: str = "amount_paise",
) -> int:
    pipeline = [
        {"$match": {"merchant_id": merchant_id, **match}},
        {"$group": {"_id": None, "total": {"$sum": f"${field}"}}},
    ]
    rows = await aggregate(collection, pipeline)
    if not rows:
        return 0
    return int(rows[0].get("total") or 0)


async def count_docs(collection: str, merchant_id: str, match: dict[str, Any]) -> int:
    return await get_db()[collection].count_documents({"merchant_id": merchant_id, **match})


def since_filter(field: str, since: datetime | None) -> dict[str, Any]:
    if since is None:
        return {}
    return {field: {"$gte": since}}
