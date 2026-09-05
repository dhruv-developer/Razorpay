from __future__ import annotations

from typing import Any

from app.agents.base import proposal_shell, upsert_agent_registry
from app.db import find_many


class CashflowAgent:
    agent_id = "cashflow_agent"
    capabilities = ["detect_liquidity_gap", "propose_payout_delay"]

    async def propose(self, merchant_id: str, state: dict[str, Any]) -> dict[str, Any] | None:
        await upsert_agent_registry(self.agent_id, self.capabilities)
        breach = float(state.get("reserve_breach_probability") or 0)
        scheduled = int(state.get("scheduled_payouts_paise") or 0)
        gap = int(state.get("reserve_gap_paise") or 0)
        if breach < 0.3 or scheduled <= 0:
            return None
        payouts = await find_many(
            "payouts",
            {"merchant_id": merchant_id, "status": {"$in": ["scheduled", "delayed"]}},
            sort=[("amount_paise", -1)],
            limit=20,
        )
        if not payouts:
            return None
        target = max(gap, int(scheduled * 0.4))
        chosen = payouts[0]
        amount = min(int(chosen.get("amount_paise") or 0), scheduled)
        if amount <= 0:
            amount = min(target, scheduled)
        return proposal_shell(
            self.agent_id,
            self.capabilities,
            "payout.delay",
            amount,
            "Projected cash falls below the merchant cash reserve; delay a non-critical payout.",
            {"liquidity_paise": amount, "reserve_breach_delta": -0.4},
            {"level": "medium", "customer_impact": "none", "vendor_impact": "delay"},
            min(0.93, 0.7 + breach * 0.25),
            "reversible",
            ["payout.delay"],
            ["state:reserve_breach_probability", "state:scheduled_payouts_paise", f"payout:{chosen.get('payout_id')}"],
            {
                "payout_id": chosen.get("payout_id"),
                "duration_hours": 12,
                "vendor_id": chosen.get("vendor_id"),
            },
        )
