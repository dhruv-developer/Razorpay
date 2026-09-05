from __future__ import annotations

import math
from typing import Any

from app.db import get_db, replace_one
from app.engines.feature_store import get_feature
from app.engines.state_engine import get_current_state
from app.timeutil import utcnow

# Domain edges only. Strength is measured from stored series; the LLM never invents these.
DOMAIN_EDGES = [
    ("upi_failure_rate", "failure_rate", "increases"),
    ("failure_rate", "success_rate", "decreases"),
    ("failure_rate", "gmv_paise", "decreases"),
    ("success_rate", "gmv_paise", "increases"),
    ("pending_settlement", "projected_cash", "increases_when_processed"),
    ("delayed_settlement", "projected_cash", "decreases"),
    ("overdue_receivables", "projected_cash", "decreases"),
    ("scheduled_payouts", "projected_cash", "decreases"),
    ("refund_rate", "cash", "decreases"),
    ("open_disputes", "operational_risk", "increases"),
]


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = min(len(xs), len(ys))
    if n < 5:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx < 1e-12 or dy < 1e-12:
        return None
    return max(-1.0, min(1.0, num / (dx * dy)))


async def _series(merchant_id: str, name: str, window: str = "24h") -> dict[Any, float]:
    """The stored series for one feature, keyed by its time bucket."""
    cursor = (
        get_db()
        .feature_series.find({"merchant_id": merchant_id, "name": name, "window": window})
        .sort("bucket", 1)
        .limit(120)
    )
    return {doc["bucket"]: float(doc.get("value") or 0) async for doc in cursor}


def _pair(
    source: dict[Any, float], destination: dict[Any, float]
) -> tuple[list[float], list[float]]:
    """Align two feature series on the buckets they share.

    Buckets where both features are zero are windows in which nothing happened,
    not observations of a zero relationship. Correlating over them inverts the
    sign of anything complementary - `failure_rate` and `success_rate` sum to 1
    on every window with traffic, so their true correlation is -1, but a run of
    empty windows drags the measured value positive.
    """
    buckets = sorted(set(source) & set(destination))
    xs: list[float] = []
    ys: list[float] = []
    for bucket in buckets:
        x, y = source[bucket], destination[bucket]
        if x == 0 and y == 0:
            continue
        xs.append(x)
        ys.append(y)
    return xs, ys


async def rebuild_causal_graph(merchant_id: str) -> dict[str, Any]:
    now = utcnow()
    state = await get_current_state(merchant_id)
    edges: list[dict[str, Any]] = []
    for source, dest, relationship in DOMAIN_EDGES:
        src_values, dst_values = _pair(
            await _series(merchant_id, source), await _series(merchant_id, dest)
        )
        corr = _pearson(src_values, dst_values)
        samples = len(src_values)
        if corr is None:
            strength = _structural_strength(source, dest, state)
            confidence = 0.35 if samples < 5 else 0.5
        else:
            strength = corr
            confidence = min(0.95, 0.45 + samples / 80)
        edge = {
            "merchant_id": merchant_id,
            "source": source,
            "destination": dest,
            "relationship": relationship,
            "strength": round(float(strength), 4),
            "confidence": round(confidence, 4),
            "samples": samples,
            "updated_at": now,
        }
        edges.append(edge)
        await replace_one(
            "causal_edges",
            {"merchant_id": merchant_id, "source": source, "destination": dest},
            edge,
            upsert=True,
        )
    return {"merchant_id": merchant_id, "edges": edges, "updated_at": now}


def _structural_strength(source: str, dest: str, state: dict[str, Any] | None) -> float:
    if not state:
        return 0.0
    mapping = {
        ("failure_rate", "gmv_paise"): -min(0.95, state.get("failure_rate_24h", 0) * 6),
        ("upi_failure_rate", "failure_rate"): min(0.95, state.get("upi_failure_rate_24h", 0) * 5),
        ("delayed_settlement", "projected_cash"): -min(
            0.9, state.get("delayed_settlement_paise", 0) / max(state.get("cash_paise", 1), 1)
        ),
        ("overdue_receivables", "projected_cash"): -min(
            0.9, state.get("overdue_receivables_paise", 0) / max(state.get("cash_paise", 1), 1)
        ),
        ("scheduled_payouts", "projected_cash"): -min(
            0.95, state.get("scheduled_payouts_paise", 0) / max(state.get("cash_paise", 1), 1)
        ),
    }
    return float(mapping.get((source, dest), 0.0))


async def explain_cash_and_revenue(merchant_id: str) -> dict[str, Any]:
    state = await get_current_state(merchant_id) or {}
    graph = await rebuild_causal_graph(merchant_id)
    drivers: list[dict[str, Any]] = []

    def add(claim: str, impact_paise: int, evidence_ids: list[str], confidence: float) -> None:
        if impact_paise == 0:
            return
        drivers.append(
            {
                "claim": claim,
                "impact_paise": int(impact_paise),
                "evidence_ids": evidence_ids,
                "confidence": round(confidence, 4),
            }
        )

    add(
        "Delayed settlements have not yet credited cash.",
        int(state.get("delayed_settlement_paise") or 0),
        ["state:delayed_settlement_paise", "collection:settlements"],
        0.92,
    )
    add(
        "Overdue receivables remain uncollected.",
        int(state.get("overdue_receivables_paise") or 0),
        ["state:overdue_receivables_paise", "collection:invoices"],
        0.9,
    )
    add(
        "Scheduled payouts are committed outflows.",
        int(state.get("scheduled_payouts_paise") or 0),
        ["state:scheduled_payouts_paise", "collection:payouts"],
        0.93,
    )
    fail_24 = float(state.get("failure_rate_24h") or 0)
    fail_7 = float(state.get("failure_rate_7d") or 0)
    failed_gmv = int(await get_feature(merchant_id, "failed_gmv_paise", "24h") or 0)
    if fail_24 > fail_7 and failed_gmv:
        add(
            "Payment failures reduced captured GMV versus the merchant 7-day baseline.",
            failed_gmv,
            ["feature:failed_gmv_paise:24h", "feature:failure_rate:24h", "feature:failure_rate:7d"],
            0.86,
        )
    upi = float(state.get("upi_failure_rate_24h") or 0)
    if upi > max(fail_7, 0.05):
        add(
            "UPI failure rate is elevated relative to the merchant baseline.",
            int(failed_gmv * min(1.0, upi / max(fail_24, 1e-6))) if fail_24 else failed_gmv,
            ["feature:upi_failure_rate:24h"],
            0.8,
        )
    drivers.sort(key=lambda d: abs(d["impact_paise"]), reverse=True)
    revenue_delta = float(state.get("revenue_delta") or 0)
    cash_story = "Cash is constrained by committed outflows and delayed inflows." if state.get(
        "reserve_breach_probability", 0
    ) >= 0.35 else "Cash is currently inside the merchant reserve band."
    return {
        "merchant_id": merchant_id,
        "revenue_delta": revenue_delta,
        "cash_paise": state.get("cash_paise", 0),
        "projected_cash_24h_paise": state.get("projected_cash_24h_paise", 0),
        "cash_story": cash_story,
        "primary_drivers": drivers[:6],
        "edges": graph["edges"],
        "confidence": state.get("confidence", 0.7),
    }
