from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.llm.copilot import ask_copilot
from app.security import authorized_merchant

router = APIRouter(prefix="/v1/copilot", tags=["copilot"])


class ChatIn(BaseModel):
    message: str
    actions: list[dict[str, Any]] = Field(default_factory=list)
    horizon_hours: int = 48


@router.post("/ask")
async def ask(
    body: ChatIn,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> dict[str, Any]:
    extra = {}
    if body.actions:
        extra = {"actions": body.actions, "horizon_hours": body.horizon_hours}
    return await ask_copilot(principal["merchant_id"], body.message, extra)
