from __future__ import annotations

from typing import Any

from app.db import find_many, get_db, insert_one
from app.ids import new_id
from app.timeutil import utcnow

KINDS = {"factual", "behavioral", "preference", "historical", "policy"}


async def remember(
    merchant_id: str,
    kind: str,
    text: str,
    structured: dict[str, Any] | None = None,
    source: str = "system",
) -> dict[str, Any]:
    if kind not in KINDS:
        kind = "factual"
    doc = {
        "memory_id": new_id("mem"),
        "merchant_id": merchant_id,
        "kind": kind,
        "text": text,
        "structured": structured or {},
        "source": source,
        "created_at": utcnow(),
    }
    await insert_one("memories", doc)
    return doc


async def list_memories(merchant_id: str, kind: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"merchant_id": merchant_id}
    if kind:
        query["kind"] = kind
    return await find_many("memories", query, sort=[("created_at", -1)], limit=limit)


def _tokens(text: str) -> set[str]:
    return {t for t in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if len(t) > 2}


async def semantic_search(merchant_id: str, query: str, limit: int = 8) -> list[dict[str, Any]]:
    q = _tokens(query)
    rows = await list_memories(merchant_id, limit=200)
    scored = []
    for row in rows:
        overlap = len(q & _tokens(row.get("text") or ""))
        if overlap:
            scored.append((overlap, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[:limit]]


async def seed_structured_memories(merchant_id: str, merchant_name: str, policy: dict[str, Any]) -> None:
    existing = await get_db().memories.find_one({"merchant_id": merchant_id, "kind": "policy"})
    if existing:
        return
    reserve = int(policy.get("cash_reserve_minimum_paise") or 0)
    await remember(
        merchant_id,
        "factual",
        f"{merchant_name} is the merchant entity modelled in the world graph.",
        {"merchant_name": merchant_name},
        source="bootstrap",
    )
    await remember(
        merchant_id,
        "policy",
        f"Minimum cash reserve is {reserve} paise.",
        {"cash_reserve_minimum_paise": reserve},
        source="policy",
    )
    if policy.get("payout_automatic_limit_paise"):
        await remember(
            merchant_id,
            "policy",
            f"Payouts above {policy['payout_automatic_limit_paise']} paise require approval.",
            {"payout_automatic_limit_paise": policy["payout_automatic_limit_paise"]},
            source="policy",
        )
