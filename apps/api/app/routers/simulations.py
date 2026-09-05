from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.engines.simulation import compare_options, simulate_actions
from app.security import authorized_merchant

router = APIRouter(prefix="/v1/simulations", tags=["simulations"])


class SimAction(BaseModel):
    type: str
    amount: int = 0
    duration_hours: int | None = None
    payout_id: str | None = None
    invoice_ids: list[str] | None = None
    payment_ids: list[str] | None = None


class SimulationRequest(BaseModel):
    actions: list[SimAction] = Field(default_factory=list)
    horizon_hours: int = 48


class CompareRequest(BaseModel):
    options: list[dict[str, Any]]
    horizon_hours: int = 48


@router.post("")
async def create_simulation(
    body: SimulationRequest,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> dict[str, Any]:
    actions = [a.model_dump(exclude_none=True) for a in body.actions]
    return await simulate_actions(principal["merchant_id"], actions, body.horizon_hours)


@router.post("/compare")
async def compare(
    body: CompareRequest,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> dict[str, Any]:
    rows = await compare_options(principal["merchant_id"], body.options, body.horizon_hours)
    return {"options": rows}
