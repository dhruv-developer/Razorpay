from __future__ import annotations

from typing import Any

from app.db import get_db, replace_one
from app.engines.state_engine import load_policy
from app.timeutil import utcnow

REVERSIBILITY_LEVEL = {
    "observe": 0,
    "invoice.dunning.draft": 1,
    "receivable.recover": 1,
    "retry.config.update": 2,
    "payment.retry": 2,
    "payout.delay": 2,
    "refund.create": 3,
    "payout.create": 3,
}

AUTONOMY_MAX_LEVEL = {
    "observe": 0,
    "recommend": 1,
    "draft": 1,
    "bounded": 2,
    "autonomous": 3,
}


async def save_policy(merchant_id: str, policy: dict[str, Any]) -> dict[str, Any]:
    doc = {**policy, "merchant_id": merchant_id, "updated_at": utcnow()}
    await replace_one("policies", {"merchant_id": merchant_id}, doc, upsert=True)
    return doc


def action_level(action_type: str) -> int:
    return REVERSIBILITY_LEVEL.get(action_type, 3)


def autonomy_allows(autonomy: str, action_type: str) -> bool:
    return action_level(action_type) <= AUTONOMY_MAX_LEVEL.get(autonomy, 1)


async def evaluate_policy(merchant_id: str, action: dict[str, Any]) -> dict[str, Any]:
    policy = await load_policy(merchant_id)
    action_type = action.get("type") or action.get("action_type")
    amount = int(action.get("amount") or action.get("amount_paise") or 0)
    reasons: list[str] = []
    requires_approval = False
    allowed = True

    if action_type in {"payout.create", "payout.delay"}:
        limit = int(policy.get("payout_automatic_limit_paise") or 0)
        if limit and amount > limit:
            requires_approval = True
            reasons.append(f"Payout amount {amount} exceeds automatic limit {limit}.")
    if action_type == "refund.create":
        limit = int(policy.get("automatic_refund_maximum_paise") or 0)
        if limit and amount > limit:
            requires_approval = True
            reasons.append(f"Refund amount {amount} exceeds automatic maximum {limit}.")
        if not limit:
            requires_approval = True
            reasons.append("Refunds require approval when no automatic maximum is configured.")
    if action_level(action_type) >= 3:
        requires_approval = True
        reasons.append("Financial actions require merchant approval.")
    if action_level(action_type) >= 2 and policy.get("autonomy_level", "recommend") in {"observe", "recommend", "draft"}:
        requires_approval = True
        reasons.append("Merchant autonomy level does not allow unattended execution.")
    if policy.get("marketing_require_approval") and action_type in {"marketing.spend"}:
        requires_approval = True
        reasons.append("Marketing spend requires approval.")

    merchant = await get_db().merchants.find_one({"merchant_id": merchant_id})
    if merchant and not merchant.get("active", True):
        allowed = False
        reasons.append("Merchant is inactive.")

    return {
        "allowed": allowed,
        "requires_approval": requires_approval,
        "reasons": reasons,
        "policy": {
            "cash_reserve_minimum_paise": policy.get("cash_reserve_minimum_paise"),
            "payout_automatic_limit_paise": policy.get("payout_automatic_limit_paise"),
            "automatic_refund_maximum_paise": policy.get("automatic_refund_maximum_paise"),
            "autonomy_level": policy.get("autonomy_level"),
        },
        "action_level": action_level(action_type or ""),
    }
