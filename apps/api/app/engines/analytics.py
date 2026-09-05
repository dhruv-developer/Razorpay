"""Merchant-scoped analytics roll-ups for the admin console.

Everything here is derived from the same Mongo collections the agents read, so
the console shows exactly what the brain saw - no separate reporting store.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.db import aggregate_grouped, find_many, get_db
from app.engines.attention import unresolved_money
from app.engines.prediction import latest_forecast
from app.engines.state_engine import get_current_state, load_policy
from app.timeutil import utcnow


def _day_key(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def _empty_days(days: int, end: datetime | None = None) -> list[str]:
    end = (end or utcnow()).replace(hour=0, minute=0, second=0, microsecond=0)
    return [_day_key(end - timedelta(days=i)) for i in range(days - 1, -1, -1)]


def _safe_rate(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(numerator / denominator, 6)


async def payments_daily(merchant_id: str, days: int = 30) -> list[dict[str, Any]]:
    """Per-day captured / failed / refunded payment volume and count."""
    since = utcnow() - timedelta(days=days)
    rows = await aggregate_grouped(
        "payments",
        [
            {"$match": {"merchant_id": merchant_id, "created_at": {"$gte": since}}},
            {
                "$group": {
                    "_id": {
                        "day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                        "status": "$status",
                    },
                    "amount": {"$sum": "$amount_paise"},
                    "count": {"$sum": 1},
                }
            },
        ],
    )
    buckets: dict[str, dict[str, Any]] = {
        day: {
            "date": day,
            "captured_paise": 0,
            "failed_paise": 0,
            "refunded_paise": 0,
            "captured_count": 0,
            "failed_count": 0,
            "refunded_count": 0,
        }
        for day in _empty_days(days)
    }
    for row in rows:
        key = row["_id"]["day"]
        status = row["_id"].get("status") or "unknown"
        bucket = buckets.setdefault(
            key,
            {
                "date": key,
                "captured_paise": 0,
                "failed_paise": 0,
                "refunded_paise": 0,
                "captured_count": 0,
                "failed_count": 0,
                "refunded_count": 0,
            },
        )
        if status in {"captured", "failed", "refunded"}:
            bucket[f"{status}_paise"] += int(row.get("amount") or 0)
            bucket[f"{status}_count"] += int(row.get("count") or 0)
    series = [buckets[key] for key in sorted(buckets)]
    for point in series:
        attempts = point["captured_count"] + point["failed_count"]
        point["attempts"] = attempts
        # A day with no attempts has no rate. Reporting 0% would draw a cliff in
        # the chart that never happened, so leave it null and let the line break.
        point["success_rate"] = _safe_rate(point["captured_count"], attempts) if attempts else None
        point["failure_rate"] = _safe_rate(point["failed_count"], attempts) if attempts else None
    return series


async def _dimension_breakdown(merchant_id: str, field: str, days: int) -> list[dict[str, Any]]:
    since = utcnow() - timedelta(days=days)
    rows = await aggregate_grouped(
        "payments",
        [
            {"$match": {"merchant_id": merchant_id, "created_at": {"$gte": since}}},
            {
                "$group": {
                    "_id": {"key": f"${field}", "status": "$status"},
                    "amount": {"$sum": "$amount_paise"},
                    "count": {"$sum": 1},
                }
            },
        ],
    )
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["_id"].get("key") or "unknown"
        status = row["_id"].get("status") or "unknown"
        entry = merged.setdefault(
            key,
            {"key": key, "captured": 0, "failed": 0, "refunded": 0, "gmv_paise": 0, "failed_paise": 0},
        )
        count = int(row.get("count") or 0)
        amount = int(row.get("amount") or 0)
        if status in entry:
            entry[status] += count
        if status == "captured":
            entry["gmv_paise"] += amount
        if status == "failed":
            entry["failed_paise"] += amount
    out = []
    for entry in merged.values():
        attempts = entry["captured"] + entry["failed"]
        entry["attempts"] = attempts
        entry["failure_rate"] = _safe_rate(entry["failed"], attempts)
        entry["success_rate"] = _safe_rate(entry["captured"], attempts)
        out.append(entry)
    out.sort(key=lambda e: e["gmv_paise"], reverse=True)
    return out


async def conversion_funnel(merchant_id: str, days: int = 30) -> list[dict[str, Any]]:
    since = utcnow() - timedelta(days=days)
    db = get_db()
    scope = {"merchant_id": merchant_id, "created_at": {"$gte": since}}
    orders = await db.orders.count_documents(scope)
    attempted = await db.payments.count_documents(scope)
    captured = await db.payments.count_documents({**scope, "status": "captured"})
    refunded = await db.payments.count_documents({**scope, "status": "refunded"})
    settled = await db.settlements.count_documents({**scope, "status": "processed"})
    stages = [
        {"stage": "Orders created", "value": orders},
        {"stage": "Payment attempted", "value": attempted},
        {"stage": "Captured", "value": captured},
        {"stage": "Settled batches", "value": settled},
        {"stage": "Refunded", "value": refunded},
    ]
    top = max(orders, attempted, 1)
    for stage in stages:
        stage["share"] = _safe_rate(stage["value"], top)
    return stages


async def action_stats(merchant_id: str) -> dict[str, Any]:
    by_status = await aggregate_grouped(
        "actions",
        [
            {"$match": {"merchant_id": merchant_id}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}, "amount": {"$sum": "$amount_paise"}}},
        ],
    )
    by_type = await aggregate_grouped(
        "actions",
        [
            {"$match": {"merchant_id": merchant_id}},
            {"$group": {"_id": "$action_type", "count": {"$sum": 1}, "amount": {"$sum": "$amount_paise"}}},
        ],
    )
    by_agent = await aggregate_grouped(
        "actions",
        [
            {"$match": {"merchant_id": merchant_id}},
            {"$group": {"_id": "$agent_id", "count": {"$sum": 1}, "amount": {"$sum": "$amount_paise"}}},
        ],
    )

    def shape(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = [
            {"key": row["_id"] or "unknown", "count": int(row["count"]), "amount_paise": int(row.get("amount") or 0)}
            for row in rows
        ]
        out.sort(key=lambda r: r["count"], reverse=True)
        return out

    statuses = shape(by_status)
    total = sum(s["count"] for s in statuses)
    verified = next((s["count"] for s in statuses if s["key"] == "VERIFIED"), 0)
    failed = next((s["count"] for s in statuses if s["key"] == "FAILED"), 0)
    pending = next((s["count"] for s in statuses if s["key"] == "PENDING_APPROVAL"), 0)
    return {
        "by_status": statuses,
        "by_type": shape(by_type),
        "by_agent": shape(by_agent),
        "total": total,
        "verified": verified,
        "failed": failed,
        "pending_approval": pending,
        "verification_rate": _safe_rate(verified, verified + failed),
    }


async def outcome_accuracy(merchant_id: str, limit: int = 120) -> dict[str, Any]:
    rows = await find_many(
        "outcomes",
        {"merchant_id": merchant_id},
        sort=[("created_at", -1)],
        limit=limit,
    )
    points = [
        {
            "outcome_id": row.get("outcome_id"),
            "agent_id": row.get("agent_id"),
            "action_id": row.get("action_id"),
            "expected_impact_paise": int(row.get("expected_impact_paise") or 0),
            "actual_impact_paise": int(row.get("actual_impact_paise") or 0),
            "prediction_error": row.get("prediction_error"),
            "result": row.get("result"),
            "created_at": row.get("created_at"),
        }
        for row in rows
    ]
    errors = [float(p["prediction_error"]) for p in points if p["prediction_error"] is not None]
    positive = len([p for p in points if p["result"] == "positive"])
    return {
        "points": points,
        "count": len(points),
        "mean_absolute_error": round(sum(errors) / len(errors), 4) if errors else None,
        "success_rate": _safe_rate(positive, len(points)),
        "net_actual_impact_paise": sum(p["actual_impact_paise"] for p in points),
        "net_expected_impact_paise": sum(p["expected_impact_paise"] for p in points),
    }


async def event_stats(merchant_id: str, days: int = 14) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    by_type = await aggregate_grouped(
        "events",
        [
            {"$match": {"merchant_id": merchant_id}},
            {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ],
    )
    daily = await aggregate_grouped(
        "events",
        [
            {"$match": {"merchant_id": merchant_id, "timestamp": {"$gte": since}}},
            {
                "$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
                    "count": {"$sum": 1},
                }
            },
        ],
    )
    by_source = await aggregate_grouped(
        "events",
        [
            {"$match": {"merchant_id": merchant_id}},
            {"$group": {"_id": "$source", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ],
    )
    buckets = {day: 0 for day in _empty_days(days)}
    for row in daily:
        buckets[row["_id"]] = int(row["count"])
    total = await get_db().events.count_documents({"merchant_id": merchant_id})
    return {
        "total": total,
        "by_type": [{"key": r["_id"], "count": int(r["count"])} for r in by_type],
        "by_source": [{"key": r["_id"] or "unknown", "count": int(r["count"])} for r in by_source],
        "daily": [{"date": day, "count": count} for day, count in sorted(buckets.items())],
    }


async def state_history(merchant_id: str, limit: int = 60) -> list[dict[str, Any]]:
    rows = await find_many(
        "merchant_states",
        {"merchant_id": merchant_id},
        sort=[("computed_at", -1)],
        limit=limit,
    )
    rows.reverse()
    return [
        {
            "computed_at": row.get("computed_at"),
            "label": row.get("label"),
            "cash_paise": int(row.get("cash_paise") or 0),
            "projected_cash_24h_paise": int(row.get("projected_cash_24h_paise") or 0),
            "cash_reserve_minimum_paise": int(row.get("cash_reserve_minimum_paise") or 0),
            "reserve_breach_probability": float(row.get("reserve_breach_probability") or 0),
            "failure_rate_24h": float(row.get("failure_rate_24h") or 0),
            "operational_risk": float(row.get("operational_risk") or 0),
            "revenue_24h_paise": int(row.get("revenue_24h_paise") or 0),
        }
        for row in rows
    ]


async def agent_leaderboard(merchant_id: str) -> list[dict[str, Any]]:
    from app.agents.orchestrator import AGENTS
    from app.agents.base import get_trust

    db = get_db()
    rows = []
    known = {a.agent_id for a in AGENTS} | {"orchestrator", "human"}
    trust_docs = await find_many("agent_trust", {"merchant_id": merchant_id}, limit=50)
    known |= {d.get("agent_id") for d in trust_docs if d.get("agent_id")}
    capabilities = {a.agent_id: a.capabilities for a in AGENTS}
    for agent_id in sorted(known):
        trust = await get_trust(merchant_id, agent_id)
        outcomes = await find_many(
            "outcomes", {"merchant_id": merchant_id, "agent_id": agent_id}, limit=300
        )
        errors = [float(o["prediction_error"]) for o in outcomes if o.get("prediction_error") is not None]
        actions = await db.actions.count_documents({"merchant_id": merchant_id, "agent_id": agent_id})
        runs = await db.agent_runs.count_documents({"merchant_id": merchant_id, "agent_id": agent_id})
        rows.append(
            {
                "agent_id": agent_id,
                "capabilities": capabilities.get(agent_id, []),
                "trust": float(trust.get("trust") or 0),
                "autonomy": trust.get("autonomy"),
                "calibration": float(trust.get("calibration") or 0),
                "successful_actions": int(trust.get("successful_actions") or 0),
                "failed_actions": int(trust.get("failed_actions") or 0),
                "policy_violations": int(trust.get("policy_violations") or 0),
                "actions": actions,
                "proposals": runs,
                "outcomes": len(outcomes),
                "net_impact_paise": sum(int(o.get("actual_impact_paise") or 0) for o in outcomes),
                "mean_absolute_error": round(sum(errors) / len(errors), 4) if errors else None,
            }
        )
    rows.sort(key=lambda r: (r["outcomes"], r["trust"]), reverse=True)
    return rows


async def entity_totals(merchant_id: str) -> dict[str, Any]:
    db = get_db()
    counts: dict[str, int] = {}
    for name in (
        "orders",
        "payments",
        "refunds",
        "invoices",
        "settlements",
        "payouts",
        "disputes",
        "customers",
        "products",
        "vendors",
        "events",
        "actions",
        "approvals",
        "recommendations",
        "agent_runs",
        "outcomes",
        "alerts",
        "simulations",
        "memories",
        "audit_logs",
        "predictions",
        "merchant_states",
        "features",
        "feature_series",
        "causal_edges",
        "relationships",
    ):
        counts[name] = await db[name].count_documents({"merchant_id": merchant_id})
    return counts


async def status_breakdown(merchant_id: str, collection: str) -> list[dict[str, Any]]:
    rows = await aggregate_grouped(
        collection,
        [
            {"$match": {"merchant_id": merchant_id}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}, "amount": {"$sum": "$amount_paise"}}},
            {"$sort": {"count": -1}},
        ],
    )
    return [
        {"key": r["_id"] or "unknown", "count": int(r["count"]), "amount_paise": int(r.get("amount") or 0)}
        for r in rows
    ]


async def top_customers(merchant_id: str, limit: int = 10) -> list[dict[str, Any]]:
    rows = await aggregate_grouped(
        "payments",
        [
            {"$match": {"merchant_id": merchant_id, "status": "captured"}},
            {
                "$group": {
                    "_id": "$customer_id",
                    "gmv_paise": {"$sum": "$amount_paise"},
                    "payments": {"$sum": 1},
                }
            },
            {"$sort": {"gmv_paise": -1}},
            {"$limit": limit},
        ],
    )
    return [
        {"customer_id": r["_id"], "gmv_paise": int(r["gmv_paise"]), "payments": int(r["payments"])}
        for r in rows
        if r["_id"]
    ]


async def analytics_bundle(merchant_id: str, days: int = 30) -> dict[str, Any]:
    """One call that backs the whole admin analytics screen."""
    days = max(3, min(days, 120))
    state = await get_current_state(merchant_id) or {}
    payments_series = await payments_daily(merchant_id, days)
    captured_total = sum(p["captured_paise"] for p in payments_series)
    failed_total = sum(p["failed_paise"] for p in payments_series)
    captured_count = sum(p["captured_count"] for p in payments_series)
    failed_count = sum(p["failed_count"] for p in payments_series)
    actions = await action_stats(merchant_id)
    outcomes = await outcome_accuracy(merchant_id)
    recommendations = await aggregate_grouped(
        "recommendations",
        [
            {"$match": {"merchant_id": merchant_id}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ],
    )
    return {
        "merchant_id": merchant_id,
        "generated_at": utcnow(),
        "range_days": days,
        "headline": {
            "gmv_paise": captured_total,
            "failed_gmv_paise": failed_total,
            "captured_count": captured_count,
            "failed_count": failed_count,
            "success_rate": _safe_rate(captured_count, captured_count + failed_count),
            "average_order_value_paise": int(captured_total / captured_count) if captured_count else 0,
            "cash_paise": int(state.get("cash_paise") or 0),
            "projected_cash_24h_paise": int(state.get("projected_cash_24h_paise") or 0),
            "reserve_breach_probability": float(state.get("reserve_breach_probability") or 0),
            "operational_risk": float(state.get("operational_risk") or 0),
            "label": state.get("label"),
        },
        "payments_daily": payments_series,
        "method_breakdown": await _dimension_breakdown(merchant_id, "method", days),
        "channel_breakdown": await _dimension_breakdown(merchant_id, "channel", days),
        "funnel": await conversion_funnel(merchant_id, days),
        "unresolved_money": await unresolved_money(merchant_id),
        "settlements": await status_breakdown(merchant_id, "settlements"),
        "payouts": await status_breakdown(merchant_id, "payouts"),
        "invoices": await status_breakdown(merchant_id, "invoices"),
        "disputes": await status_breakdown(merchant_id, "disputes"),
        "refunds": await status_breakdown(merchant_id, "refunds"),
        "actions": actions,
        "outcomes": outcomes,
        "agents": await agent_leaderboard(merchant_id),
        "events": await event_stats(merchant_id, min(days, 30)),
        "state_history": await state_history(merchant_id),
        "forecast": await latest_forecast(merchant_id),
        "top_customers": await top_customers(merchant_id),
        "recommendations": [{"key": r["_id"] or "unknown", "count": int(r["count"])} for r in recommendations],
        "policy": await load_policy(merchant_id),
        "totals": await entity_totals(merchant_id),
    }
