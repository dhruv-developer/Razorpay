from __future__ import annotations

from typing import Any

from app.agents.base import proposal_shell, upsert_agent_registry
from app.db import find_many


class PaymentRecoveryAgent:
    agent_id = "payment_recovery_agent"
    capabilities = ["identify_failed_payments", "propose_retry"]

    async def propose(self, merchant_id: str, state: dict[str, Any]) -> dict[str, Any] | None:
        await upsert_agent_registry(self.agent_id, self.capabilities)
        failed = int(state.get("failed_recovery_paise") or 0)
        fail_now = float(state.get("failure_rate_24h") or 0)
        fail_base = float(state.get("failure_rate_7d") or 0)
        if failed <= 0:
            return None
        if fail_now < 0.04 and fail_now <= fail_base * 1.1:
            return None
        payments = await find_many(
            "payments",
            {"merchant_id": merchant_id, "status": "failed"},
            sort=[("created_at", -1)],
            limit=50,
        )
        eligible = [
            p
            for p in payments
            if p.get("failure_code") in {"TIMEOUT", "GATEWAY_ERROR", "NETWORK_ERROR", None}
        ]
        amount = sum(int(p.get("amount_paise") or 0) for p in eligible) or failed
        return proposal_shell(
            self.agent_id,
            self.capabilities,
            "payment.retry",
            amount,
            "Retry eligible failed payments concentrated in the current failure spike.",
            {"expected_recovered_gmv_paise": int(amount * 0.28)},
            {"level": "low", "customer_impact": "retry_notification", "vendor_impact": "none"},
            0.78,
            "reversible",
            ["payment.retry"],
            ["state:failed_recovery_paise", "feature:failure_rate:24h"],
            {"payment_ids": [p.get("payment_id") for p in eligible[:30]], "method_filter": "upi"},
        )
