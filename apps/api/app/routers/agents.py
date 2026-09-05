from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.agents.orchestrator import AGENTS, agent_performance, collect_proposals, orchestrate
from app.db import find_many, find_one
from app.security import authorized_merchant

router = APIRouter(tags=["agents"])


@router.get("/v1/agent-performance")
async def performance(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    return {"agents": await agent_performance(principal["merchant_id"])}


@router.post("/v1/orchestrate")
async def run_orch(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    return await orchestrate(principal["merchant_id"])


@router.get("/internal/agents/{agent}/capabilities")
async def capabilities(agent: str) -> dict[str, Any]:
    found = next((a for a in AGENTS if a.agent_id == agent), None)
    if not found:
        raise HTTPException(status_code=404, detail="Unknown agent")
    return {"agent_id": found.agent_id, "capabilities": found.capabilities}


@router.get("/internal/agents/{agent}/health")
async def agent_health(agent: str, principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    found = next((a for a in AGENTS if a.agent_id == agent), None)
    if not found:
        raise HTTPException(status_code=404, detail="Unknown agent")
    trust = await find_one("agent_trust", {"merchant_id": principal["merchant_id"], "agent_id": agent})
    return {"agent_id": agent, "status": "active", "trust": trust}


@router.post("/internal/agents/{agent}/propose")
async def propose(agent: str, principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    found = next((a for a in AGENTS if a.agent_id == agent), None)
    if not found:
        raise HTTPException(status_code=404, detail="Unknown agent")
    from app.engines.state_engine import get_current_state

    state = await get_current_state(principal["merchant_id"]) or {}
    proposal = await found.propose(principal["merchant_id"], state)
    return {"proposal": proposal}


@router.get("/internal/agents")
async def list_internal() -> dict[str, Any]:
    return {"agents": [{"agent_id": a.agent_id, "capabilities": a.capabilities} for a in AGENTS]}


@router.get("/v1/agent-runs")
async def runs(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    return {
        "runs": await find_many(
            "agent_runs",
            {"merchant_id": principal["merchant_id"]},
            sort=[("created_at", -1)],
            limit=50,
        )
    }
