from __future__ import annotations

from typing import Any

from app.agents.base import get_trust
from app.agents.cashflow import CashflowAgent
from app.agents.payment_recovery import PaymentRecoveryAgent
from app.agents.payout import PayoutAgent
from app.agents.receivables import ReceivablesAgent
from app.db import insert_one
from app.engines.simulation import compare_options, simulate_actions
from app.engines.state_engine import get_current_state, load_policy
from app.ids import new_id
from app.timeutil import utcnow

AGENTS = [CashflowAgent(), ReceivablesAgent(), PaymentRecoveryAgent(), PayoutAgent()]


def _value(sim: dict[str, Any], weights: dict[str, float]) -> float:
    growth = float(sim.get("expected_recovered_gmv_paise") or 0)
    cash = float(sim.get("expected_business_impact_paise") or 0)
    risk_pen = {"low": 0.05, "medium": 0.25, "high": 0.6}.get(sim.get("risk"), 0.3)
    risk_pen += float(sim.get("reserve_breach_probability") or 0)
    return (
        weights.get("growth", 0.3) * growth
        + weights.get("cash", 0.5) * cash
        - weights.get("risk", 0.2) * risk_pen * max(abs(cash), 1)
    )


async def collect_proposals(merchant_id: str) -> list[dict[str, Any]]:
    state = await get_current_state(merchant_id) or {}
    proposals = []
    for agent in AGENTS:
        proposal = await agent.propose(merchant_id, state)
        if not proposal:
            continue
        trust = await get_trust(merchant_id, proposal["agent_id"])
        proposal["trust"] = trust.get("trust")
        proposal["agent_autonomy"] = trust.get("autonomy")
        proposals.append(proposal)
        await insert_one(
            "agent_runs",
            {
                "run_id": new_id("run"),
                "merchant_id": merchant_id,
                "agent_id": proposal["agent_id"],
                "created_at": utcnow(),
                "proposal": proposal,
            },
        )
    return proposals


async def orchestrate(merchant_id: str) -> dict[str, Any]:
    state = await get_current_state(merchant_id) or {}
    policy = await load_policy(merchant_id)
    weights = policy.get("weights") or {"growth": 0.3, "cash": 0.5, "risk": 0.2}
    proposals = await collect_proposals(merchant_id)
    do_nothing = {
        "label": "Do nothing",
        "actions": [{"type": "observe", "amount": 0}],
    }
    options = [do_nothing]
    for proposal in proposals:
        options.append(
            {
                "label": proposal["agent_id"],
                "actions": [proposal["proposal"]],
            }
        )
    if len(proposals) >= 2:
        combo = [p["proposal"] for p in proposals if p["proposal"].get("type") != "payout.create"]
        if combo:
            options.append({"label": "Coordinated plan", "actions": combo})

    compared = await compare_options(merchant_id, options, horizon_hours=48)
    for sim in compared:
        sim["objective_value"] = _value(sim, weights)
    compared.sort(key=lambda s: s["objective_value"], reverse=True)
    winner = compared[0]
    rejected = []
    for sim in compared[1:]:
        rejected.append(
            {
                "label": sim.get("label"),
                "reason": _reject_reason(winner, sim),
                "reserve_breach_probability": sim.get("reserve_breach_probability"),
                "projected_cash_paise": sim.get("projected_cash_paise"),
            }
        )

    recommended_actions = winner.get("actions") or []
    rec_id = new_id("rec")
    recommendation = {
        "recommendation_id": rec_id,
        "merchant_id": merchant_id,
        "created_at": utcnow(),
        "problem": _problem_statement(state),
        "evidence": {
            "cash_paise": state.get("cash_paise"),
            "projected_cash_24h_paise": state.get("projected_cash_24h_paise"),
            "reserve_breach_probability": state.get("reserve_breach_probability"),
            "delayed_settlement_paise": state.get("delayed_settlement_paise"),
            "overdue_receivables_paise": state.get("overdue_receivables_paise"),
            "scheduled_payouts_paise": state.get("scheduled_payouts_paise"),
            "failure_rate_24h": state.get("failure_rate_24h"),
        },
        "proposed_action": recommended_actions,
        "expected_impact": {
            "projected_cash_paise": winner.get("projected_cash_paise"),
            "reserve_breach_probability": winner.get("reserve_breach_probability"),
            "business_impact_paise": winner.get("expected_business_impact_paise"),
        },
        "confidence": winner.get("confidence"),
        "risk": winner.get("risk"),
        "alternatives": rejected,
        "why_this": "Highest expected business value under merchant objective weights and reserve constraint.",
        "status": "GENERATED",
        "simulation_id": winner.get("simulation_id"),
        "proposals": proposals,
    }
    await insert_one("recommendations", recommendation)
    return {
        "recommendation": recommendation,
        "proposals": proposals,
        "simulations": compared,
        "winner": winner,
    }


def _problem_statement(state: dict[str, Any]) -> str:
    if float(state.get("reserve_breach_probability") or 0) >= 0.35:
        return "Projected cash falls below the merchant reserve within 24h."
    if float(state.get("failure_rate_24h") or 0) > float(state.get("failure_rate_7d") or 0) * 1.25:
        return "Payment failure rate is deteriorating versus the merchant baseline."
    if int(state.get("overdue_receivables_paise") or 0) > 0:
        return "Overdue receivables are constraining inflows."
    return "No material financial stress detected; hold current policy."


def _reject_reason(winner: dict[str, Any], other: dict[str, Any]) -> str:
    if other.get("label") == "Do nothing" and (other.get("reserve_breach_probability") or 0) > (
        winner.get("reserve_breach_probability") or 0
    ):
        return f"Do nothing leaves reserve-breach probability at {other.get('reserve_breach_probability')}."
    if (other.get("reserve_breach_probability") or 1) > (winner.get("reserve_breach_probability") or 1):
        return "Higher reserve-breach probability than the recommended plan."
    if (other.get("expected_business_impact_paise") or 0) < (winner.get("expected_business_impact_paise") or 0):
        return "Lower expected cash impact under the merchant objective weights."
    return "Inferior objective score after simulation."


async def agent_performance(merchant_id: str) -> list[dict[str, Any]]:
    from app.db import find_many

    rows = []
    for agent in AGENTS:
        trust = await get_trust(merchant_id, agent.agent_id)
        outcomes = await find_many("outcomes", {"merchant_id": merchant_id, "agent_id": agent.agent_id}, limit=200)
        recovered = sum(int(o.get("actual_impact_paise") or 0) for o in outcomes)
        rows.append({**trust, "net_impact_paise": recovered, "outcomes": len(outcomes)})
    return rows
