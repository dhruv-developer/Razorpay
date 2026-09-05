from __future__ import annotations

from typing import Any

from app.agents.base import proposal_shell, upsert_agent_registry
from app.db import find_many


class ReceivablesAgent:
    agent_id = "receivables_agent"
    capabilities = ["identify_overdue_invoices", "draft_collection_message"]

    async def propose(self, merchant_id: str, state: dict[str, Any]) -> dict[str, Any] | None:
        await upsert_agent_registry(self.agent_id, self.capabilities)
        overdue = int(state.get("overdue_receivables_paise") or 0)
        if overdue <= 0:
            return None
        invoices = await find_many(
            "invoices",
            {"merchant_id": merchant_id, "status": "overdue"},
            sort=[("amount_paise", -1)],
            limit=20,
        )
        invoice_ids = [inv.get("invoice_id") for inv in invoices if inv.get("invoice_id")]
        return proposal_shell(
            self.agent_id,
            self.capabilities,
            "receivable.recover",
            overdue,
            "Recover overdue invoices that are delaying cash inflows.",
            {"expected_inflow_paise": int(overdue * 0.4), "invoices": len(invoice_ids)},
            {"level": "medium", "customer_impact": "dunning", "vendor_impact": "none"},
            0.82,
            "draft",
            ["invoice.dunning"],
            ["state:overdue_receivables_paise", "collection:invoices"],
            {"invoice_ids": invoice_ids, "mode": "dunning_draft"},
        )
