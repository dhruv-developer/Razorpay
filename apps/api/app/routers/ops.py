from __future__ import annotations

from typing import Annotated, Any

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db import find_many, find_one
from app.engines.state_engine import get_current_state
from app.money import format_inr
from app.security import authorized_merchant

router = APIRouter(prefix="/ops", tags=["ops"], include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
templates.env.filters["inr"] = format_inr


@router.get("", response_class=HTMLResponse)
async def ops_home(
    request: Request,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> HTMLResponse:
    state = await get_current_state(principal["merchant_id"]) or {}
    recs = await find_many("recommendations", {"merchant_id": principal["merchant_id"]}, sort=[("created_at", -1)], limit=8)
    actions = await find_many("actions", {"merchant_id": principal["merchant_id"]}, sort=[("created_at", -1)], limit=8)
    return templates.TemplateResponse(
        request,
        "home.html",
        {"principal": principal, "state": state, "recommendations": recs, "actions": actions},
    )


@router.get("/events", response_class=HTMLResponse)
async def ops_events(
    request: Request,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> HTMLResponse:
    events = await find_many("events", {"merchant_id": principal["merchant_id"]}, sort=[("timestamp", -1)], limit=80)
    return templates.TemplateResponse(request, "events.html", {"principal": principal, "events": events})


@router.get("/actions", response_class=HTMLResponse)
async def ops_actions(
    request: Request,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> HTMLResponse:
    actions = await find_many("actions", {"merchant_id": principal["merchant_id"]}, sort=[("created_at", -1)], limit=80)
    return templates.TemplateResponse(request, "actions.html", {"principal": principal, "actions": actions})


@router.get("/agents", response_class=HTMLResponse)
async def ops_agents(
    request: Request,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> HTMLResponse:
    runs = await find_many("agent_runs", {"merchant_id": principal["merchant_id"]}, sort=[("created_at", -1)], limit=40)
    return templates.TemplateResponse(request, "agents.html", {"principal": principal, "runs": runs})


@router.get("/recommendations/{recommendation_id}", response_class=HTMLResponse)
async def ops_rec(
    recommendation_id: str,
    request: Request,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> HTMLResponse:
    rec = await find_one(
        "recommendations",
        {"recommendation_id": recommendation_id, "merchant_id": principal["merchant_id"]},
    )
    return templates.TemplateResponse(request, "recommendation.html", {"principal": principal, "rec": rec})
