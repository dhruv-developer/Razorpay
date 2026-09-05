from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import Any

from app.db import get_db, insert_one
from app.engines.aggregates import count_docs, sum_field
from app.engines.state_engine import get_current_state, load_policy
from app.ids import new_id
from app.timeutil import utcnow


def _breach_prob(projected_cash: int, reserve: int) -> float:
    if reserve <= 0:
        return 0.05 if projected_cash > 0 else 0.7
    if projected_cash >= reserve:
        return max(0.02, min(0.25, (reserve * 0.12) / max(projected_cash, 1)))
    gap = reserve - projected_cash
    return min(0.97, 0.45 + gap / reserve * 0.55)


async def _retry_success_rate(merchant_id: str) -> float:
    retries = await count_docs("payments", merchant_id, {"retry_of": {"$exists": True, "$ne": None}})
    if retries < 5:
        captured = await count_docs("payments", merchant_id, {"status": "captured"})
        failed = await count_docs("payments", merchant_id, {"status": "failed"})
        total = captured + failed
        return max(0.18, min(0.55, captured / total if total else 0.28))
    recovered = await count_docs(
        "payments", merchant_id, {"retry_of": {"$exists": True, "$ne": None}, "status": "captured"}
    )
    return recovered / retries


async def _invoice_collection_rate(merchant_id: str) -> float:
    paid = await count_docs("invoices", merchant_id, {"status": "paid"})
    overdue = await count_docs("invoices", merchant_id, {"status": "overdue"})
    open_ = await count_docs("invoices", merchant_id, {"status": "open"})
    denom = paid + overdue + open_
    if denom < 3:
        return 0.4
    return max(0.15, min(0.75, paid / denom))


async def simulate_actions(
    merchant_id: str,
    actions: list[dict[str, Any]],
    horizon_hours: int = 48,
) -> dict[str, Any]:
    state = deepcopy(await get_current_state(merchant_id) or {})
    policy = await load_policy(merchant_id)
    reserve = int(policy.get("cash_reserve_minimum_paise") or state.get("cash_reserve_minimum_paise") or 0)
    retry_rate = await _retry_success_rate(merchant_id)
    collect_rate = await _invoice_collection_rate(merchant_id)
    baseline_cash = int(state.get("projected_cash_24h_paise") or state.get("cash_paise") or 0)
    working = deepcopy(state)
    notes: list[str] = []
    recovered_gmv = 0
    customer_friction = 0.0
    operational_exposure = 0

    for action in actions:
        atype = action.get("type") or action.get("action_type")
        amount = int(action.get("amount") or action.get("amount_paise") or 0)
        if atype == "payout.delay":
            delay_h = int(action.get("duration_hours") or action.get("delay_hours") or 12)
            delayable = min(
                amount or int(working.get("scheduled_payouts_paise") or 0),
                int(working.get("scheduled_payouts_paise") or 0),
            )
            if horizon_hours <= delay_h:
                working["projected_cash_24h_paise"] = int(working.get("projected_cash_24h_paise") or 0) + delayable
                working["scheduled_payouts_paise"] = int(working.get("scheduled_payouts_paise") or 0) - delayable
                notes.append(f"Delay keeps {delayable} paise in cash for the {horizon_hours}h horizon.")
            else:
                fraction = delay_h / max(horizon_hours, 1)
                working["projected_cash_24h_paise"] = int(working.get("projected_cash_24h_paise") or 0) + int(
                    delayable * fraction
                )
                notes.append(f"Partial delay benefit {fraction:.2f} of {delayable} paise.")
            operational_exposure += int(delayable * 0.05)
        elif atype == "receivable.recover":
            overdue = int(working.get("overdue_receivables_paise") or 0)
            target = min(amount or overdue, overdue)
            expected = int(target * collect_rate)
            working["projected_cash_24h_paise"] = int(working.get("projected_cash_24h_paise") or 0) + expected
            working["overdue_receivables_paise"] = overdue - expected
            recovered_gmv += expected
            customer_friction += 0.15
            notes.append(f"Collections use historical paid-invoice rate {collect_rate:.2f}.")
        elif atype == "payment.retry":
            failed = int(working.get("failed_recovery_paise") or 0)
            target = min(amount or failed, failed)
            expected = int(target * retry_rate)
            working["projected_cash_24h_paise"] = int(working.get("projected_cash_24h_paise") or 0) + int(expected * 0.35)
            working["revenue_24h_paise"] = int(working.get("revenue_24h_paise") or 0) + expected
            working["failed_recovery_paise"] = failed - expected
            recovered_gmv += expected
            customer_friction += 0.25
            notes.append(f"Retries use observed retry/capture rate {retry_rate:.2f}.")
        elif atype == "payout.create":
            working["projected_cash_24h_paise"] = int(working.get("projected_cash_24h_paise") or 0) - amount
            working["scheduled_payouts_paise"] = int(working.get("scheduled_payouts_paise") or 0) + amount
            notes.append("Creating a payout reduces projected cash immediately.")
        elif atype in {"observe", "invoice.dunning.draft"}:
            notes.append("Read-only or draft action; cash path unchanged.")
        elif atype == "refund.create":
            working["projected_cash_24h_paise"] = int(working.get("projected_cash_24h_paise") or 0) - amount
            customer_friction -= 0.2
            notes.append("Refund reduces cash and slightly lowers customer friction.")

    projected = int(working.get("projected_cash_24h_paise") or 0)
    baseline_breach = _breach_prob(baseline_cash, reserve)
    projected_breach = _breach_prob(projected, reserve)
    impact = projected - baseline_cash
    risk = "low"
    if projected_breach >= 0.65 or customer_friction >= 0.5:
        risk = "high"
    elif projected_breach >= 0.3 or customer_friction >= 0.25:
        risk = "medium"

    result = {
        "simulation_id": new_id("sim"),
        "merchant_id": merchant_id,
        "created_at": utcnow(),
        "horizon_hours": horizon_hours,
        "actions": actions,
        "baseline_cash_paise": int(state.get("cash_paise") or 0),
        "baseline_projected_cash_paise": baseline_cash,
        "projected_cash_paise": projected,
        "reserve_paise": reserve,
        "baseline_reserve_breach_probability": round(baseline_breach, 4),
        "reserve_breach_probability": round(projected_breach, 4),
        "expected_business_impact_paise": impact,
        "expected_recovered_gmv_paise": recovered_gmv,
        "operational_exposure_paise": operational_exposure,
        "customer_friction": round(max(0.0, customer_friction), 4),
        "risk": risk,
        "confidence": round(min(0.92, 0.6 + retry_rate * 0.2 + collect_rate * 0.15), 4),
        "notes": notes,
        "projected_state": {
            "cash_paise": projected,
            "overdue_receivables_paise": working.get("overdue_receivables_paise"),
            "scheduled_payouts_paise": working.get("scheduled_payouts_paise"),
            "failed_recovery_paise": working.get("failed_recovery_paise"),
            "revenue_24h_paise": working.get("revenue_24h_paise"),
        },
    }
    await insert_one("simulations", result)
    return result


async def compare_options(merchant_id: str, options: list[dict[str, Any]], horizon_hours: int = 48) -> list[dict[str, Any]]:
    compared = []
    for option in options:
        sim = await simulate_actions(merchant_id, option.get("actions") or [], horizon_hours)
        sim["label"] = option.get("label") or option.get("id") or sim["simulation_id"]
        compared.append(sim)
    return compared
