from __future__ import annotations

from typing import Any

from app.agents.orchestrator import orchestrate
from app.engines.anomaly import detect_anomalies
from app.engines.attention import attention_queue, unresolved_money
from app.engines.causal import explain_cash_and_revenue
from app.engines.feature_store import recompute_features
from app.engines.prediction import forecast_merchant
from app.engines.state_engine import get_current_state, recompute_merchant_state
from app.timeutil import utcnow


async def run_brain_cycle(merchant_id: str) -> dict[str, Any]:
    features = await recompute_features(merchant_id)
    state = await recompute_merchant_state(merchant_id)
    anomalies = await detect_anomalies(merchant_id)
    causal = await explain_cash_and_revenue(merchant_id)
    forecast = await forecast_merchant(merchant_id)
    attention = await attention_queue(merchant_id, refresh_anomalies=False)
    money = await unresolved_money(merchant_id)
    should_orchestrate = bool(anomalies) or float(state.get("reserve_breach_probability") or 0) >= 0.25
    orchestration = None
    if should_orchestrate:
        orchestration = await orchestrate(merchant_id)
    return {
        "merchant_id": merchant_id,
        "ran_at": utcnow(),
        "features_computed": len(features),
        "state": state,
        "anomalies": anomalies,
        "causal": causal,
        "forecast": forecast,
        "attention": attention,
        "unresolved_money": money,
        "orchestration": orchestration,
    }


async def merchant_health(merchant_id: str) -> dict[str, Any]:
    state = await get_current_state(merchant_id)
    if not state:
        state = await recompute_merchant_state(merchant_id)
    forecast = await forecast_merchant(merchant_id)
    return {"state": state, "forecast": forecast, "weather": forecast.get("weather")}
