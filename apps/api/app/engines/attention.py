from __future__ import annotations

from typing import Any

from app.engines.anomaly import detect_anomalies
from app.engines.causal import explain_cash_and_revenue
from app.engines.state_engine import get_current_state
from app.money import rupees


def _score(impact: int, urgency: float, confidence: float, reversibility: float) -> float:
    return abs(impact) * urgency * confidence * reversibility


async def attention_queue(merchant_id: str, refresh_anomalies: bool = False) -> list[dict[str, Any]]:
    state = await get_current_state(merchant_id) or {}
    causal = await explain_cash_and_revenue(merchant_id)
    anomalies = await detect_anomalies(merchant_id) if refresh_anomalies else []
    items: list[dict[str, Any]] = []

    gap = int(state.get("reserve_gap_paise") or 0)
    breach = float(state.get("reserve_breach_probability") or 0)
    if breach >= 0.25:
        items.append(
            {
                "id": "cash_reserve",
                "title": "Cash reserve breach likely" if breach >= 0.5 else "Cash tightness forming",
                "severity": "high" if breach >= 0.5 else "medium",
                "impact_paise": gap or int(state.get("scheduled_payouts_paise") or 0),
                "urgency": min(1.0, 0.4 + breach),
                "confidence": float(state.get("confidence") or 0.7),
                "reversibility": 0.7,
                "why": causal["cash_story"],
                "evidence_ids": ["state:reserve_breach_probability", "state:projected_cash_24h_paise"],
                "cta": "See why",
            }
        )

    fail_now = float(state.get("failure_rate_24h") or 0)
    fail_base = float(state.get("failure_rate_7d") or 0)
    failed = int(state.get("failed_recovery_paise") or 0)
    if fail_now > fail_base * 1.25 and fail_now >= 0.05:
        items.append(
            {
                "id": "payment_failures",
                "title": "Payment failures rising",
                "severity": "high" if fail_now >= 0.1 else "medium",
                "impact_paise": failed,
                "urgency": min(1.0, fail_now * 6),
                "confidence": 0.84,
                "reversibility": 0.85,
                "why": f"24h failure rate {fail_now:.1%} vs 7d baseline {fail_base:.1%}.",
                "evidence_ids": ["feature:failure_rate:24h", "feature:failure_rate:7d"],
                "cta": "Investigate",
            }
        )

    overdue = int(state.get("overdue_receivables_paise") or 0)
    if overdue > 0:
        items.append(
            {
                "id": "overdue_receivables",
                "title": "Overdue receivables outstanding",
                "severity": "medium",
                "impact_paise": overdue,
                "urgency": 0.55,
                "confidence": 0.9,
                "reversibility": 0.8,
                "why": "Uncollected invoices are delaying inflows.",
                "evidence_ids": ["state:overdue_receivables_paise"],
                "cta": "Recover",
            }
        )

    delayed = int(state.get("delayed_settlement_paise") or 0)
    if delayed > 0:
        items.append(
            {
                "id": "settlement_delay",
                "title": "Settlements delayed",
                "severity": "medium",
                "impact_paise": delayed,
                "urgency": 0.6,
                "confidence": 0.91,
                "reversibility": 0.4,
                "why": "Captured payments have not reached the cash account.",
                "evidence_ids": ["state:delayed_settlement_paise"],
                "cta": "Inspect",
            }
        )

    for anomaly in anomalies:
        items.append(
            {
                "id": anomaly["alert_id"],
                "title": f"Anomaly in {anomaly['name']}",
                "severity": anomaly["severity"],
                "impact_paise": failed if "fail" in anomaly["name"] else 0,
                "urgency": 0.7 if anomaly["severity"] == "high" else 0.45,
                "confidence": min(0.9, 0.55 + abs(float(anomaly.get("z_score") or 0)) / 6),
                "reversibility": 0.6,
                "why": f"Current {anomaly['current']} vs baseline {anomaly['baseline']:.4f}.",
                "evidence_ids": anomaly.get("evidence_ids") or [],
                "cta": "Review",
            }
        )

    for item in items:
        item["score"] = _score(
            int(item["impact_paise"]),
            float(item["urgency"]),
            float(item["confidence"]),
            float(item["reversibility"]),
        )
        item["impact_display"] = rupees(item["impact_paise"])
    items.sort(key=lambda x: x["score"], reverse=True)
    return items[:8]


async def unresolved_money(merchant_id: str) -> dict[str, Any]:
    state = await get_current_state(merchant_id) or {}
    buckets = [
        {"key": "pending_settlements", "label": "Pending settlements", "amount_paise": int(state.get("pending_settlement_paise") or 0), "recoverable": 0.9},
        {"key": "overdue_receivables", "label": "Overdue receivables", "amount_paise": int(state.get("overdue_receivables_paise") or 0), "recoverable": 0.4},
        {"key": "disputes", "label": "Disputes", "amount_paise": int(state.get("open_disputes_paise") or 0), "recoverable": 0.25},
        {"key": "failed_recovery", "label": "Failed payment recovery", "amount_paise": int(state.get("failed_recovery_paise") or 0), "recoverable": 0.3},
        {"key": "pending_refunds", "label": "Pending refunds", "amount_paise": int(state.get("pending_refunds_paise") or 0), "recoverable": 0.0},
        {"key": "scheduled_payouts", "label": "Scheduled payouts", "amount_paise": int(state.get("scheduled_payouts_paise") or 0), "recoverable": 0.0},
    ]
    total = sum(b["amount_paise"] for b in buckets)
    recoverable = int(sum(b["amount_paise"] * b["recoverable"] for b in buckets if b["key"] != "scheduled_payouts"))
    return {
        "merchant_id": merchant_id,
        "buckets": buckets,
        "total_paise": total,
        "recoverable_48h_paise": recoverable,
        "currency": "INR",
    }
