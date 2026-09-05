from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.db import get_db, replace_one, strip_id, update_one
from app.engines.aggregates import count_docs, sum_field
from app.engines.feature_store import get_feature
from app.money import rupees
from app.timeutil import utcnow


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _health_from_failure(failure_rate: float, baseline: float) -> float:
    if failure_rate <= baseline:
        return 1.0
    return _clamp01(1.0 - (failure_rate - baseline) / max(baseline, 0.02) / 4.0)


async def current_cash(merchant_id: str) -> int:
    account = await get_db().cash_accounts.find_one({"merchant_id": merchant_id})
    if not account:
        return 0
    return int(account.get("balance_paise") or 0)


async def load_policy(merchant_id: str) -> dict[str, Any]:
    doc = strip_id(await get_db().policies.find_one({"merchant_id": merchant_id}))
    if not doc:
        return {
            "merchant_id": merchant_id,
            "cash_reserve_minimum_paise": 0,
            "automatic_refund_maximum_paise": 0,
            "payout_automatic_limit_paise": 0,
            "autonomy_level": "recommend",
            "weights": {"growth": 0.3, "cash": 0.5, "risk": 0.2},
        }
    return doc


async def recompute_merchant_state(merchant_id: str) -> dict[str, Any]:
    now = utcnow()
    policy = await load_policy(merchant_id)
    cash = await current_cash(merchant_id)
    gmv_24h = int(await get_feature(merchant_id, "gmv_paise", "24h") or 0)
    gmv_7d = int(await get_feature(merchant_id, "gmv_paise", "7d") or 0)
    gmv_prev = max(gmv_7d - gmv_24h, 0)
    daily_baseline = int(gmv_prev / 6) if gmv_prev else gmv_24h
    revenue_delta = ((gmv_24h - daily_baseline) / daily_baseline) if daily_baseline else 0.0

    pending_settlement = await sum_field(
        "settlements", merchant_id, {"status": {"$in": ["pending", "delayed"]}}
    )
    delayed_settlement = await sum_field("settlements", merchant_id, {"status": "delayed"})
    receivables = await sum_field("invoices", merchant_id, {"status": {"$in": ["open", "overdue"]}})
    overdue = await sum_field("invoices", merchant_id, {"status": "overdue"})
    scheduled_payouts = await sum_field(
        "payouts", merchant_id, {"status": {"$in": ["scheduled", "delayed"]}}
    )
    due_payouts_24h = await sum_field(
        "payouts",
        merchant_id,
        {
            "status": {"$in": ["scheduled", "delayed"]},
            "created_at": {"$lte": now},
        },
    )
    pending_refunds = await sum_field("refunds", merchant_id, {"status": "pending"})
    open_disputes = await sum_field("disputes", merchant_id, {"status": "open"})
    failed_recovery = await sum_field(
        "payments",
        merchant_id,
        {"status": "failed", "created_at": {"$gte": now - timedelta(hours=48)}},
    )
    payroll = await sum_field("employees", merchant_id, {}, field="scheduled_payroll_paise")

    failure_24h = float(await get_feature(merchant_id, "failure_rate", "24h") or 0.0)
    failure_7d = float(await get_feature(merchant_id, "failure_rate", "7d") or 0.0)
    success_24h = float(await get_feature(merchant_id, "success_rate", "24h") or 0.0)
    success_7d = float(await get_feature(merchant_id, "success_rate", "7d") or 0.0)
    refund_24h = float(await get_feature(merchant_id, "refund_rate", "24h") or 0.0)
    upi_fail_24h = float(await get_feature(merchant_id, "upi_failure_rate", "24h") or 0.0)
    aov = int(await get_feature(merchant_id, "average_order_value_paise", "24h") or 0)

    expected_inflows = pending_settlement + overdue
    expected_outflows = scheduled_payouts + pending_refunds + payroll
    projected_cash_24h = cash + int(0.7 * pending_settlement) + int(0.35 * overdue) - scheduled_payouts - pending_refunds
    reserve = int(policy.get("cash_reserve_minimum_paise") or 0)
    gap = max(reserve - projected_cash_24h, 0)
    reserve_breach_probability = 0.0
    if reserve > 0:
        if projected_cash_24h >= reserve:
            reserve_breach_probability = _clamp01((reserve * 0.15) / max(projected_cash_24h, 1))
        else:
            reserve_breach_probability = _clamp01(0.45 + gap / max(reserve, 1) * 0.55)

    liquidity = _clamp01(cash / max(reserve * 1.5 if reserve else expected_outflows or cash or 1, 1))
    transaction_health = _health_from_failure(failure_24h, max(failure_7d, 0.03))
    returning_customers = await count_docs("customers", merchant_id, {"returning": True})
    total_customers = await count_docs("customers", merchant_id, {})
    customer_health = _clamp01(returning_customers / total_customers) if total_customers else 0.5
    settlement_health = _clamp01(1.0 - delayed_settlement / max(pending_settlement + delayed_settlement, 1))
    dispute_risk = _clamp01(open_disputes / max(gmv_24h, 1))
    fraud_risk = _clamp01(dispute_risk * 1.4 + refund_24h)
    operational_risk = _clamp01(
        0.4 * reserve_breach_probability + 0.35 * failure_24h / 0.2 + 0.25 * (1 - settlement_health)
    )
    growth = _clamp01(0.5 + revenue_delta)
    cashflow_forecast = projected_cash_24h
    confidence = _clamp01(0.55 + min(total_customers, 400) / 800 + min((gmv_7d > 0), 1) * 0.2)

    label = "stable"
    if reserve_breach_probability >= 0.65 or failure_24h >= 0.12:
        label = "critical"
    elif reserve_breach_probability >= 0.35 or failure_24h >= 0.08 or revenue_delta < -0.06:
        label = "watch"
    elif growth > 0.6 and transaction_health > 0.8:
        label = "healthy"

    state = {
        "merchant_id": merchant_id,
        "computed_at": now,
        "is_current": True,
        "currency": "INR",
        "label": label,
        "cash_paise": cash,
        "revenue_24h_paise": gmv_24h,
        "revenue_7d_paise": gmv_7d,
        "revenue_delta": round(revenue_delta, 6),
        "daily_gmv_baseline_paise": daily_baseline,
        "pending_settlement_paise": pending_settlement,
        "delayed_settlement_paise": delayed_settlement,
        "receivables_paise": receivables,
        "overdue_receivables_paise": overdue,
        "scheduled_payouts_paise": scheduled_payouts,
        "due_payouts_paise": due_payouts_24h,
        "pending_refunds_paise": pending_refunds,
        "open_disputes_paise": open_disputes,
        "failed_recovery_paise": failed_recovery,
        "payroll_scheduled_paise": payroll,
        "expected_inflows_paise": expected_inflows,
        "expected_outflows_paise": expected_outflows,
        "projected_cash_24h_paise": projected_cash_24h,
        "cash_reserve_minimum_paise": reserve,
        "reserve_gap_paise": gap,
        "reserve_breach_probability": round(reserve_breach_probability, 4),
        "failure_rate_24h": failure_24h,
        "failure_rate_7d": failure_7d,
        "success_rate_24h": success_24h,
        "success_rate_7d": success_7d,
        "refund_rate_24h": refund_24h,
        "upi_failure_rate_24h": upi_fail_24h,
        "average_order_value_paise": aov,
        "liquidity": round(liquidity, 4),
        "revenue": round(_clamp01(gmv_24h / max(daily_baseline, 1)), 4),
        "transaction_health": round(transaction_health, 4),
        "customer_health": round(customer_health, 4),
        "receivables": round(_clamp01(1 - overdue / max(receivables, 1)), 4) if receivables else 1.0,
        "payables": round(_clamp01(1 - scheduled_payouts / max(cash + scheduled_payouts, 1)), 4),
        "settlement_health": round(settlement_health, 4),
        "fraud_risk": round(fraud_risk, 4),
        "dispute_risk": round(dispute_risk, 4),
        "operational_risk": round(operational_risk, 4),
        "growth": round(growth, 4),
        "cashflow_forecast": cashflow_forecast,
        "agent_activity": 0,
        "confidence": round(confidence, 4),
        "display": {
            "cash": rupees(cash),
            "revenue_24h": rupees(gmv_24h),
            "projected_cash_24h": rupees(projected_cash_24h),
        },
    }

    await update_one("merchant_states", {"merchant_id": merchant_id, "is_current": True}, {"$set": {"is_current": False}})
    await replace_one(
        "merchant_states",
        {"merchant_id": merchant_id, "computed_at": now},
        state,
        upsert=True,
    )
    return state


async def get_current_state(merchant_id: str) -> dict[str, Any] | None:
    doc = strip_id(await get_db().merchant_states.find_one({"merchant_id": merchant_id, "is_current": True}))
    if not doc:
        return await recompute_merchant_state(merchant_id)
    return doc
