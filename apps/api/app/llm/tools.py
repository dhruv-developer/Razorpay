from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.agents.orchestrator import collect_proposals, orchestrate
from app.engines.attention import attention_queue, unresolved_money
from app.engines.causal import explain_cash_and_revenue
from app.engines.prediction import latest_forecast
from app.engines.simulation import simulate_actions
from app.engines.state_engine import get_current_state
from app.llm.pii import strip_pii

ToolFn = Callable[[str, dict[str, Any]], Awaitable[Any]]

TOOL_PERMS = {
    "get_merchant_state": "READ",
    "get_cashflow": "READ",
    "get_payment_health": "READ",
    "get_receivables": "READ",
    "get_settlements": "READ",
    "get_active_risks": "READ",
    "simulate_action": "READ_SIMULATION",
    "get_agent_proposals": "READ",
    "get_unresolved_money": "READ",
    "run_orchestration": "READ",
}


async def get_merchant_state(merchant_id: str, _: dict[str, Any]) -> Any:
    return await get_current_state(merchant_id)


async def get_cashflow(merchant_id: str, _: dict[str, Any]) -> Any:
    state = await get_current_state(merchant_id) or {}
    forecast = await latest_forecast(merchant_id)
    return {
        "cash_paise": state.get("cash_paise"),
        "expected_inflows_paise": state.get("expected_inflows_paise"),
        "expected_outflows_paise": state.get("expected_outflows_paise"),
        "projected_cash_24h_paise": state.get("projected_cash_24h_paise"),
        "reserve_breach_probability": state.get("reserve_breach_probability"),
        "weather": forecast.get("weather"),
        "horizons": forecast.get("horizons"),
    }


async def get_payment_health(merchant_id: str, _: dict[str, Any]) -> Any:
    state = await get_current_state(merchant_id) or {}
    return {
        "success_rate_24h": state.get("success_rate_24h"),
        "failure_rate_24h": state.get("failure_rate_24h"),
        "failure_rate_7d": state.get("failure_rate_7d"),
        "upi_failure_rate_24h": state.get("upi_failure_rate_24h"),
        "failed_recovery_paise": state.get("failed_recovery_paise"),
        "refund_rate_24h": state.get("refund_rate_24h"),
    }


async def get_receivables(merchant_id: str, _: dict[str, Any]) -> Any:
    state = await get_current_state(merchant_id) or {}
    return {
        "receivables_paise": state.get("receivables_paise"),
        "overdue_receivables_paise": state.get("overdue_receivables_paise"),
    }


async def get_settlements(merchant_id: str, _: dict[str, Any]) -> Any:
    state = await get_current_state(merchant_id) or {}
    return {
        "pending_settlement_paise": state.get("pending_settlement_paise"),
        "delayed_settlement_paise": state.get("delayed_settlement_paise"),
        "settlement_health": state.get("settlement_health"),
    }


async def get_active_risks(merchant_id: str, _: dict[str, Any]) -> Any:
    state = await get_current_state(merchant_id) or {}
    return {
        "fraud_risk": state.get("fraud_risk"),
        "dispute_risk": state.get("dispute_risk"),
        "operational_risk": state.get("operational_risk"),
        "open_disputes_paise": state.get("open_disputes_paise"),
        "attention": await attention_queue(merchant_id),
    }


async def simulate_action_tool(merchant_id: str, args: dict[str, Any]) -> Any:
    actions = args.get("actions") or []
    horizon = int(args.get("horizon_hours") or 48)
    return await simulate_actions(merchant_id, actions, horizon)


async def get_agent_proposals(merchant_id: str, _: dict[str, Any]) -> Any:
    return await collect_proposals(merchant_id)


async def get_unresolved_money_tool(merchant_id: str, _: dict[str, Any]) -> Any:
    return await unresolved_money(merchant_id)


async def run_orchestration(merchant_id: str, _: dict[str, Any]) -> Any:
    result = await orchestrate(merchant_id)
    rec = result.get("recommendation") or {}
    return {
        "recommendation_id": rec.get("recommendation_id"),
        "problem": rec.get("problem"),
        "proposed_action": rec.get("proposed_action"),
        "expected_impact": rec.get("expected_impact"),
        "alternatives": rec.get("alternatives"),
        "confidence": rec.get("confidence"),
    }


async def explain_why(merchant_id: str, _: dict[str, Any]) -> Any:
    return await explain_cash_and_revenue(merchant_id)


TOOLS: dict[str, ToolFn] = {
    "get_merchant_state": get_merchant_state,
    "get_cashflow": get_cashflow,
    "get_payment_health": get_payment_health,
    "get_receivables": get_receivables,
    "get_settlements": get_settlements,
    "get_active_risks": get_active_risks,
    "simulate_action": simulate_action_tool,
    "get_agent_proposals": get_agent_proposals,
    "get_unresolved_money": get_unresolved_money_tool,
    "run_orchestration": run_orchestration,
    "explain_why": explain_why,
}


INTENT_TOOLS = {
    "why_cash": ["get_cashflow", "get_settlements", "get_receivables", "explain_why"],
    "why_revenue": ["get_payment_health", "get_merchant_state", "explain_why"],
    "what_next": ["get_merchant_state", "get_agent_proposals", "run_orchestration"],
    "what_if": ["simulate_action", "get_cashflow"],
    "health": ["get_merchant_state", "get_cashflow", "get_active_risks", "get_unresolved_money"],
    "risk": ["get_active_risks", "get_payment_health"],
    "money": ["get_unresolved_money", "get_cashflow"],
}


def route_intent(message: str) -> str:
    text = message.lower()
    if any(w in text for w in ("what if", "simulate", "delay payout", "recover")):
        return "what_if"
    if any(w in text for w in ("what should", "what do", "recommend", "action")):
        return "what_next"
    if any(w in text for w in ("revenue", "gmv", "failure", "upi")):
        return "why_revenue"
    if any(w in text for w in ("cash", "liquidity", "payout", "settlement")):
        return "why_cash"
    if any(w in text for w in ("risk", "fraud", "dispute")):
        return "risk"
    if any(w in text for w in ("money", "unresolved", "where")):
        return "money"
    return "health"


async def run_tools(merchant_id: str, names: list[str], args: dict[str, Any] | None = None) -> dict[str, Any]:
    collected: dict[str, Any] = {}
    for name in names:
        fn = TOOLS.get(name)
        if not fn:
            continue
        collected[name] = strip_pii(await fn(merchant_id, args or {}))
    return collected
