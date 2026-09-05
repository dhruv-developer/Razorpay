from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import find_many, find_one
from app.safety.executor import create_action, decide_approval, execute_action
from app.security import authorized_merchant

router = APIRouter(prefix="/v1/actions", tags=["actions"])


class ActionIn(BaseModel):
    type: str
    amount: int = 0
    reason: str | None = None
    agent_id: str = "human"
    recommendation_id: str | None = None
    duration_hours: int | None = None
    payout_id: str | None = None
    invoice_ids: list[str] | None = None
    payment_ids: list[str] | None = None
    vendor_id: str | None = None


class DecisionIn(BaseModel):
    token: str | None = None


@router.post("")
async def post_action(
    body: ActionIn,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    rec_id = payload.pop("recommendation_id", None)
    return await create_action(principal["merchant_id"], payload, principal, recommendation_id=rec_id)


@router.get("")
async def list_actions(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    return {
        "actions": await find_many(
            "actions",
            {"merchant_id": principal["merchant_id"]},
            sort=[("created_at", -1)],
            limit=80,
        )
    }


@router.get("/{action_id}")
async def get_action(
    action_id: str,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> dict[str, Any]:
    doc = await find_one("actions", {"action_id": action_id, "merchant_id": principal["merchant_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Action not found")
    return doc


@router.post("/{action_id}/approve")
async def approve(
    action_id: str,
    body: DecisionIn,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> dict[str, Any]:
    token = body.token
    if not token:
        approval = await find_one("approvals", {"action_id": action_id, "merchant_id": principal["merchant_id"]})
        token = (approval or {}).get("token")
    if not token:
        # already authorized financial-low actions can execute directly
        return await execute_action(action_id, principal)
    return await decide_approval(token, True, principal)


@router.post("/{action_id}/reject")
async def reject(
    action_id: str,
    body: DecisionIn,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> dict[str, Any]:
    token = body.token
    if not token:
        approval = await find_one("approvals", {"action_id": action_id, "merchant_id": principal["merchant_id"]})
        token = (approval or {}).get("token")
    if not token:
        raise HTTPException(status_code=400, detail="No approval token")
    return await decide_approval(token, False, principal)
