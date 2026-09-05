from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.db import get_db, replace_one
from app.timeutil import utcnow

LIMITS = {
    "refund.create": 20,
    "payout.create": 15,
    "payout.delay": 30,
    "payment.retry": 80,
    "receivable.recover": 40,
}


async def check_circuit(merchant_id: str, agent_id: str, action_type: str) -> dict[str, Any]:
    now = utcnow()
    window_start = now - timedelta(minutes=10)
    count = await get_db().actions.count_documents(
        {
            "merchant_id": merchant_id,
            "agent_id": agent_id,
            "action_type": action_type,
            "created_at": {"$gte": window_start},
        }
    )
    limit = LIMITS.get(action_type, 50)
    tripped = count >= limit
    doc = {
        "merchant_id": merchant_id,
        "agent_id": agent_id,
        "action_type": action_type,
        "window_count": count,
        "limit": limit,
        "tripped": tripped,
        "updated_at": now,
    }
    await replace_one(
        "circuit_breakers",
        {"merchant_id": merchant_id, "agent_id": agent_id, "action_type": action_type},
        doc,
        upsert=True,
    )
    return doc
