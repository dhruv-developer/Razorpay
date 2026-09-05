from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.db import find_many, find_one
from app.engines.attention import attention_queue, unresolved_money
from app.engines.causal import explain_cash_and_revenue
from app.engines.decision import merchant_health, run_brain_cycle
from app.engines.feature_store import get_features
from app.engines.memory import list_memories, remember
from app.engines.prediction import latest_forecast
from app.engines.state_engine import get_current_state, load_policy
from app.safety.policy import save_policy
from app.security import authorized_merchant
from pydantic import BaseModel

router = APIRouter(prefix="/v1/merchant", tags=["merchant"])


class MemoryIn(BaseModel):
    kind: str
    text: str
    structured: dict[str, Any] = {}


class PolicyIn(BaseModel):
    cash_reserve_minimum_paise: int | None = None
    automatic_refund_maximum_paise: int | None = None
    payout_automatic_limit_paise: int | None = None
    autonomy_level: str | None = None
    weights: dict[str, float] | None = None


@router.get("/state")
async def state(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    return await get_current_state(principal["merchant_id"]) or {}


@router.get("/health")
async def health(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    return await merchant_health(principal["merchant_id"])


@router.get("/cashflow")
async def cashflow(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    state_doc = await get_current_state(principal["merchant_id"]) or {}
    forecast = await latest_forecast(principal["merchant_id"])
    return {
        "cash_paise": state_doc.get("cash_paise"),
        "expected_inflows_paise": state_doc.get("expected_inflows_paise"),
        "expected_outflows_paise": state_doc.get("expected_outflows_paise"),
        "projected_cash_24h_paise": state_doc.get("projected_cash_24h_paise"),
        "reserve_breach_probability": state_doc.get("reserve_breach_probability"),
        "forecast": forecast,
    }


@router.get("/risks")
async def risks(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    state_doc = await get_current_state(principal["merchant_id"]) or {}
    return {
        "fraud_risk": state_doc.get("fraud_risk"),
        "dispute_risk": state_doc.get("dispute_risk"),
        "operational_risk": state_doc.get("operational_risk"),
        "open_disputes_paise": state_doc.get("open_disputes_paise"),
        "attention": await attention_queue(principal["merchant_id"]),
    }


@router.get("/recommendations")
async def recommendations(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    rows = await find_many(
        "recommendations",
        {"merchant_id": principal["merchant_id"]},
        sort=[("created_at", -1)],
        limit=30,
    )
    return {"recommendations": rows}


@router.get("/unresolved-money")
async def money(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    return await unresolved_money(principal["merchant_id"])


@router.get("/attention")
async def attention(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    return {"items": await attention_queue(principal["merchant_id"])}


@router.get("/why")
async def why(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    return await explain_cash_and_revenue(principal["merchant_id"])


@router.get("/features")
async def features(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    return await get_features(principal["merchant_id"])


@router.get("/policy")
async def policy(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    return await load_policy(principal["merchant_id"])


@router.put("/policy")
async def update_policy(
    body: PolicyIn,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> dict[str, Any]:
    current = await load_policy(principal["merchant_id"])
    merged = {**current, **{k: v for k, v in body.model_dump().items() if v is not None}}
    return await save_policy(principal["merchant_id"], merged)


@router.get("/memories")
async def memories(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    return {"memories": await list_memories(principal["merchant_id"])}


@router.post("/memories")
async def add_memory(
    body: MemoryIn,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> dict[str, Any]:
    return await remember(principal["merchant_id"], body.kind, body.text, body.structured, source="merchant")


@router.post("/cycle")
async def cycle(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    return await run_brain_cycle(principal["merchant_id"])


@router.get("/profile")
async def profile(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    return await find_one("merchants", {"merchant_id": principal["merchant_id"]}) or {}


@router.post("/recommendations/{recommendation_id}/act")
async def act_on_recommendation(
    recommendation_id: str,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> dict[str, Any]:
    from app.db import update_one
    from app.safety.executor import create_action

    rec = await find_one(
        "recommendations",
        {"recommendation_id": recommendation_id, "merchant_id": principal["merchant_id"]},
    )
    if not rec:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Recommendation not found")
    created = []
    for action in rec.get("proposed_action") or []:
        if (action.get("type") or action.get("action_type")) in {None, "observe"}:
            continue
        created.append(
            await create_action(
                principal["merchant_id"],
                {**action, "agent_id": action.get("agent_id") or "orchestrator"},
                principal,
                recommendation_id=recommendation_id,
            )
        )
    await update_one("recommendations", {"recommendation_id": recommendation_id}, {"$set": {"status": "VIEWED"}})
    return {"recommendation_id": recommendation_id, "actions": created}
