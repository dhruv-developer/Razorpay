from __future__ import annotations

import math
from typing import Any

from app.db import get_db, insert_one
from app.engines.feature_store import get_feature
from app.engines.state_engine import get_current_state
from app.ids import new_id
from app.timeutil import utcnow

WATCHED = [
    ("failure_rate", "24h", "higher"),
    ("upi_failure_rate", "24h", "higher"),
    ("refund_rate", "24h", "higher"),
    ("success_rate", "24h", "lower"),
    ("gmv_paise", "24h", "lower"),
]


def _z(current: float, mean: float, std: float) -> float:
    if std < 1e-9:
        if mean == 0:
            return 0.0
        return (current - mean) / max(abs(mean), 1e-6)
    return (current - mean) / std


async def _baseline(merchant_id: str, name: str, window: str) -> tuple[float, float, int]:
    cursor = (
        get_db()
        .feature_series.find({"merchant_id": merchant_id, "name": name, "window": window})
        .sort("bucket", -1)
        .limit(48)
    )
    values = [float(doc.get("value") or 0) async for doc in cursor]
    if len(values) < 3:
        current = float(await get_feature(merchant_id, name, "7d") or 0)
        return current, max(abs(current) * 0.15, 1e-4), len(values)
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / max(len(values) - 1, 1)
    return mean, math.sqrt(var), len(values)


async def detect_anomalies(merchant_id: str) -> list[dict[str, Any]]:
    state = await get_current_state(merchant_id)
    now = utcnow()
    findings: list[dict[str, Any]] = []
    for name, window, direction in WATCHED:
        current = float(await get_feature(merchant_id, name, window) or 0)
        mean, std, n = await _baseline(merchant_id, name, window)
        z = _z(current, mean, std)
        velocity = current - mean
        is_anomaly = False
        if direction == "higher" and z >= 2.0 and current > mean:
            is_anomaly = True
        if direction == "lower" and z <= -2.0 and current < mean:
            is_anomaly = True
        if name == "failure_rate" and current >= max(mean * 1.6, mean + 0.04) and current >= 0.06:
            is_anomaly = True
        if not is_anomaly:
            continue
        severity = "high" if abs(z) >= 3 else "medium"
        finding = {
            "alert_id": new_id("alrt"),
            "merchant_id": merchant_id,
            "name": name,
            "window": window,
            "current": current,
            "baseline": mean,
            "std": std,
            "z_score": round(z, 4),
            "velocity": round(velocity, 6),
            "samples": n,
            "severity": severity,
            "direction": direction,
            "created_at": now,
            "evidence_ids": [f"feature:{name}:{window}"],
        }
        findings.append(finding)
        await insert_one("alerts", finding)

    if state and state.get("reserve_breach_probability", 0) >= 0.35:
        finding = {
            "alert_id": new_id("alrt"),
            "merchant_id": merchant_id,
            "name": "reserve_breach_probability",
            "window": "24h",
            "current": state["reserve_breach_probability"],
            "baseline": 0.15,
            "std": 0.0,
            "z_score": 0.0,
            "velocity": state["reserve_breach_probability"] - 0.15,
            "samples": 1,
            "severity": "high" if state["reserve_breach_probability"] >= 0.65 else "medium",
            "direction": "higher",
            "created_at": now,
            "evidence_ids": ["state:reserve_breach_probability"],
        }
        findings.append(finding)
        await insert_one("alerts", finding)
    return findings
