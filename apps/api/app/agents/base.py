from __future__ import annotations

from typing import Any, Protocol

from app.db import get_db, replace_one, strip_id
from app.timeutil import utcnow


class Agent(Protocol):
    agent_id: str
    capabilities: list[str]

    async def propose(self, merchant_id: str, state: dict[str, Any]) -> dict[str, Any] | None: ...


async def upsert_agent_registry(agent_id: str, capabilities: list[str]) -> None:
    await replace_one(
        "agent_registry",
        {"agent_id": agent_id},
        {
            "agent_id": agent_id,
            "capabilities": capabilities,
            "status": "active",
            "updated_at": utcnow(),
        },
        upsert=True,
    )


async def get_trust(merchant_id: str, agent_id: str) -> dict[str, Any]:
    doc = strip_id(await get_db().agent_trust.find_one({"merchant_id": merchant_id, "agent_id": agent_id}))
    if doc:
        return doc
    return {
        "merchant_id": merchant_id,
        "agent_id": agent_id,
        "accuracy": 0.7,
        "calibration": 0.7,
        "successful_actions": 0,
        "failed_actions": 0,
        "policy_violations": 0,
        "rollback_rate": 0.0,
        "trust": 0.7,
        "autonomy": "recommend",
    }


async def apply_trust_update(merchant_id: str, agent_id: str, success: bool, prediction_error: float | None = None) -> dict[str, Any]:
    current = await get_trust(merchant_id, agent_id)
    trust = float(current.get("trust") or 0.7) * 0.97  # decay
    if success:
        trust = min(0.98, trust + 0.03)
        current["successful_actions"] = int(current.get("successful_actions") or 0) + 1
    else:
        trust = max(0.15, trust - 0.08)
        current["failed_actions"] = int(current.get("failed_actions") or 0) + 1
    if prediction_error is not None:
        current["calibration"] = round(max(0.1, min(0.99, 1 - min(abs(prediction_error), 1))), 4)
    current["trust"] = round(trust, 4)
    current["updated_at"] = utcnow()
    if trust < 0.4:
        current["autonomy"] = "observe"
    elif trust < 0.6:
        current["autonomy"] = "recommend"
    else:
        current["autonomy"] = current.get("autonomy") or "recommend"
    await replace_one(
        "agent_trust",
        {"merchant_id": merchant_id, "agent_id": agent_id},
        current,
        upsert=True,
    )
    return current


def proposal_shell(
    agent_id: str,
    capabilities: list[str],
    action_type: str,
    amount_paise: int,
    reason: str,
    expected_impact: dict[str, Any],
    risk: dict[str, Any],
    confidence: float,
    reversibility: str,
    required_permissions: list[str],
    evidence_ids: list[str],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "capabilities": capabilities,
        "inputs": {"amount_paise": amount_paise, **(payload or {})},
        "proposal": {
            "type": action_type,
            "amount": amount_paise,
            "amount_paise": amount_paise,
            "reason": reason,
            **(payload or {}),
        },
        "confidence": confidence,
        "expected_impact": expected_impact,
        "risk": risk,
        "required_permissions": required_permissions,
        "reversibility": reversibility,
        "evidence_ids": evidence_ids,
    }
