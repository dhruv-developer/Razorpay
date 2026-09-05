from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from app.db import get_db, insert_one, strip_id
from app.engines.aggregates import sum_field
from app.engines.state_engine import get_current_state
from app.ids import new_id
from app.timeutil import utcnow


async def _daily_captured(merchant_id: str, days: int = 21) -> list[tuple[Any, int]]:
    now = utcnow()
    series: list[tuple[Any, int]] = []
    for i in range(days, 0, -1):
        start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        total = await sum_field(
            "payments",
            merchant_id,
            {"status": "captured", "created_at": {"$gte": start, "$lt": end}},
        )
        series.append((start, total))
    return series


def _trend_forecast(values: list[float], horizon: int) -> list[float]:
    n = len(values)
    if n == 0:
        return [0.0] * horizon
    if n == 1:
        return [values[0]] * horizon
    xs = list(range(n))
    xbar = (n - 1) / 2
    ybar = sum(values) / n
    denom = sum((x - xbar) ** 2 for x in xs) or 1.0
    slope = sum((x - xbar) * (y - ybar) for x, y in zip(xs, values)) / denom
    intercept = ybar - slope * xbar
    return [max(0.0, intercept + slope * (n + i)) for i in range(horizon)]


def _residual_std(values: list[float]) -> float:
    if len(values) < 3:
        return max(abs(values[-1]) * 0.12, 1.0) if values else 1.0
    fitted = _trend_forecast(values[:-1], 1)
    # use residuals vs mean of last window
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return max(math.sqrt(var), abs(fitted[0]) * 0.05, 1.0)


async def forecast_merchant(merchant_id: str, horizon_days: int = 3) -> dict[str, Any]:
    state = await get_current_state(merchant_id) or {}
    daily = await _daily_captured(merchant_id, days=21)
    gmv_values = [float(v) for _, v in daily]
    gmv_points = _trend_forecast(gmv_values, horizon_days)
    gmv_std = _residual_std(gmv_values)

    cash = float(state.get("cash_paise") or 0)
    inflow = float(state.get("pending_settlement_paise") or 0) * 0.7 + float(
        state.get("overdue_receivables_paise") or 0
    ) * 0.25
    outflow = float(state.get("scheduled_payouts_paise") or 0) + float(state.get("pending_refunds_paise") or 0)
    daily_net = (inflow - outflow) / max(horizon_days, 1)
    cash_points = [max(0.0, cash + daily_net * (i + 1)) for i in range(horizon_days)]
    fail_now = float(state.get("failure_rate_24h") or 0)
    fail_base = float(state.get("failure_rate_7d") or fail_now)
    fail_points = [max(0.0, fail_now + (fail_now - fail_base) * (i + 1) * 0.35) for i in range(horizon_days)]

    def band(expected: float, std: float) -> dict[str, int]:
        return {
            "p10": int(max(0, expected - 1.2816 * std)),
            "p50": int(max(0, expected)),
            "p90": int(max(0, expected + 1.2816 * std)),
        }

    now = utcnow()
    horizons = []
    for i, (gmv, cash_f, fail_f) in enumerate(zip(gmv_points, cash_points, fail_points), start=1):
        item = {
            "horizon": f"{i}d",
            "revenue": band(gmv, gmv_std),
            "cash": band(cash_f, max(gmv_std * 0.4, cash * 0.05)),
            "failure_rate": {
                "p10": round(max(0, fail_f - 0.02), 4),
                "p50": round(fail_f, 4),
                "p90": round(fail_f + 0.03, 4),
            },
        }
        horizons.append(item)

    quality = min(0.93, 0.5 + len([v for v in gmv_values if v > 0]) / 30)
    doc = {
        "prediction_id": new_id("pred"),
        "merchant_id": merchant_id,
        "created_at": now,
        "model_version": "trend-residual-v1",
        "confidence": round(quality * float(state.get("confidence") or 0.7), 4),
        "data_quality": round(quality, 4),
        "horizons": horizons,
        "weather": _weather(state, cash_points),
    }
    await insert_one("predictions", doc)
    return doc


def _weather(state: dict[str, Any], cash_points: list[float]) -> list[dict[str, Any]]:
    reserve = float(state.get("cash_reserve_minimum_paise") or 0)
    labels = ["Today", "Tomorrow", "+2 days", "+3 days"]
    today = float(state.get("cash_paise") or 0)
    series = [today, *cash_points]
    out = []
    for i, cash in enumerate(series[:4]):
        if reserve <= 0:
            score = 0.8 if cash > 0 else 0.2
        else:
            score = max(0.0, min(1.0, cash / (reserve * 1.6)))
        if score >= 0.75:
            label, risk = "Healthy", "low"
        elif score >= 0.5:
            label, risk = "Moderate", "medium"
        elif score >= 0.3:
            label, risk = "Risk", "high"
        else:
            label, risk = "High risk", "critical"
        out.append(
            {
                "label": labels[i],
                "cash_paise": int(cash),
                "score": round(score, 4),
                "status": label,
                "risk": risk,
            }
        )
    return out


async def latest_forecast(merchant_id: str) -> dict[str, Any]:
    doc = strip_id(await get_db().predictions.find_one({"merchant_id": merchant_id}, sort=[("created_at", -1)]))
    if not doc:
        return await forecast_merchant(merchant_id)
    return doc
