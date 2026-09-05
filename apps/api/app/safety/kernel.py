from __future__ import annotations

from typing import Any

from app.cache import cache_set_nx
from app.db import get_db
from app.safety.circuit import check_circuit
from app.safety.policy import evaluate_policy


async def authorize_action(
    principal: dict[str, Any],
    merchant_id: str,
    action: dict[str, Any],
) -> dict[str, Any]:
    if principal.get("merchant_id") != merchant_id and "platform_admin" not in principal.get("roles", []):
        return {"ok": False, "stage": "authorization", "detail": "Caller is not authorized for this merchant."}

    policy = await evaluate_policy(merchant_id, action)
    if not policy["allowed"]:
        return {"ok": False, "stage": "policy", "detail": "; ".join(policy["reasons"]), "policy": policy}

    amount = int(action.get("amount") or action.get("amount_paise") or 0)
    if amount < 0:
        return {"ok": False, "stage": "amount_limit", "detail": "Negative amounts are not executable."}

    agent_id = action.get("agent_id") or "human"
    circuit = await check_circuit(merchant_id, agent_id, action.get("type") or action.get("action_type") or "unknown")
    if circuit.get("tripped"):
        return {
            "ok": False,
            "stage": "circuit_breaker",
            "detail": f"Agent {agent_id} exceeded {circuit['limit']} {circuit['action_type']} actions in 10 minutes.",
            "circuit": circuit,
        }

    idem_key = action.get("idempotency_key") or action.get("action_id")
    if idem_key:
        claimed = await cache_set_nx(f"act:{idem_key}", "1", ttl=86400)
        existing = await get_db().actions.find_one({"action_id": idem_key, "status": {"$in": ["EXECUTED", "VERIFIED"]}})
        if existing or not claimed:
            return {"ok": False, "stage": "idempotency", "detail": "Action already processed.", "duplicate": True}

    return {"ok": True, "stage": "authorized", "policy": policy, "circuit": circuit}
