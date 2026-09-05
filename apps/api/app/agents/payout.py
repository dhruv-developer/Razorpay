from __future__ import annotations

from typing import Any

from app.agents.base import proposal_shell, upsert_agent_registry
from app.db import find_many


class PayoutAgent:
    agent_id = "payout_agent"
    capabilities = ["protect_vendor_obligations"]

    async def propose(self, merchant_id: str, state: dict[str, Any]) -> dict[str, Any] | None:
        await upsert_agent_registry(self.agent_id, self.capabilities)
        scheduled = int(state.get("scheduled_payouts_paise") or 0)
        cash = int(state.get("cash_paise") or 0)
        reserve = int(state.get("cash_reserve_minimum_paise") or 0)
        if scheduled <= 0:
            return None
        # Only argue for paying on schedule when doing so still respects reserve.
        if cash - scheduled < reserve:
            return None
        payouts = await find_many(
            "payouts",
            {"merchant_id": merchant_id, "status": {"$in": ["scheduled", "delayed"]}},
            sort=[("created_at", 1)],
            limit=5,
        )
        if not payouts:
            return None
        first = payouts[0]
        return proposal_shell(
            self.agent_id,
            self.capabilities,
            "payout.create",
            int(first.get("amount_paise") or 0),
            "Cash remains above reserve after scheduled payouts; keep vendor obligations on time.",
            {"vendor_trust": 0.1},
            {"level": "medium", "customer_impact": "none", "vendor_impact": "on_time"},
            0.74,
            "financial",
            ["payout.create"],
            ["state:cash_paise", "state:scheduled_payouts_paise", f"payout:{first.get('payout_id')}"],
            {"payout_id": first.get("payout_id"), "vendor_id": first.get("vendor_id")},
        )
