"""Admin console API.

Gives a merchant admin full read access to every layer the brain writes -
raw entities, events, features, causal edges, predictions, simulations,
recommendations, actions, approvals, outcomes, audit logs - plus the analytics
roll-ups and the in-process self-test suite.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.cache import get_redis
from app.config import get_settings
from app.db import COLLECTIONS, aggregate_grouped, find_many, find_one, get_db
from app.engines.analytics import analytics_bundle, state_history
from app.engines.selftest import run_self_test
from app.security import authorized_merchant
from app.timeutil import as_utc, utcnow

router = APIRouter(prefix="/v1/admin", tags=["admin"])

PROCESS_STARTED_AT = utcnow()

# Collections a merchant admin may browse. Everything is merchant-scoped at query
# time; the auth/credential collections are deliberately absent.
BROWSABLE = {
    "orders",
    "payments",
    "refunds",
    "invoices",
    "settlements",
    "payouts",
    "disputes",
    "customers",
    "products",
    "vendors",
    "employees",
    "cash_accounts",
    "subscriptions",
    "events",
    "merchant_states",
    "features",
    "feature_series",
    "causal_edges",
    "predictions",
    "recommendations",
    "actions",
    "approvals",
    "agent_runs",
    "agent_trust",
    "outcomes",
    "memories",
    "alerts",
    "simulations",
    "circuit_breakers",
    "audit_logs",
    "relationships",
    "policies",
}

# Sensible default sort per collection so the browser opens on the newest rows.
DEFAULT_SORT = {
    "events": "timestamp",
    "feature_series": "bucket",
    "features": "computed_at",
    "merchant_states": "computed_at",
    "causal_edges": "updated_at",
    "agent_trust": "updated_at",
    "circuit_breakers": "updated_at",
    "cash_accounts": "updated_at",
    "policies": "updated_at",
    "relationships": "updated_at",
    "vendors": "updated_at",
    "products": "updated_at",
    "customers": "updated_at",
}

# Fields the free-text `q` filter matches against, per collection.
SEARCH_FIELDS = {
    "payments": ["payment_id", "order_id", "customer_id", "status", "method", "channel"],
    "orders": ["order_id", "customer_id", "product_id", "status", "channel"],
    "refunds": ["refund_id", "payment_id", "status", "reason"],
    "invoices": ["invoice_id", "customer_id", "status"],
    "settlements": ["settlement_id", "status"],
    "payouts": ["payout_id", "vendor_id", "status", "reason"],
    "disputes": ["dispute_id", "payment_id", "status", "reason"],
    "customers": ["customer_id", "segment", "channel"],
    "events": ["event_id", "event_type", "entity_id", "source", "trace_id"],
    "actions": ["action_id", "action_type", "status", "agent_id", "reason", "trace_id"],
    "approvals": ["action_id", "action_type", "status"],
    "recommendations": ["recommendation_id", "status", "problem"],
    "outcomes": ["outcome_id", "action_id", "agent_id", "result"],
    "agent_runs": ["run_id", "agent_id"],
    "audit_logs": ["action_id", "event", "actor"],
    "alerts": ["alert_id", "name", "severity", "direction"],
    "memories": ["memory_id", "kind", "text", "source"],
    "simulations": ["simulation_id", "label", "risk"],
    "features": ["name", "window"],
    "feature_series": ["name", "window"],
    "causal_edges": ["source", "destination", "relationship"],
    "predictions": ["prediction_id", "model_version"],
    "merchant_states": ["label"],
}


class SelfTestRequest(BaseModel):
    include_mutating: bool = False


@router.get("/system")
async def system(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    """Service health, configuration and per-collection document counts."""
    settings = get_settings()
    db = get_db()
    merchant_id = principal["merchant_id"]

    mongo: dict[str, Any] = {"connected": False}
    started = time.perf_counter()
    try:
        await db.command("ping")
        mongo = {
            "connected": True,
            "database": settings.mongo_db,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:  # noqa: BLE001 - health must report, not raise
        mongo = {"connected": False, "error": str(exc)}

    redis_client = get_redis()
    redis_state: dict[str, Any] = {"connected": False, "detail": "Not connected; idempotency falls back to Mongo."}
    if redis_client is not None:
        started = time.perf_counter()
        try:
            await redis_client.ping()
            redis_state = {"connected": True, "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
        except Exception as exc:  # noqa: BLE001
            redis_state = {"connected": False, "error": str(exc)}

    counts_all: dict[str, int] = {}
    counts_mine: dict[str, int] = {}
    for name in COLLECTIONS:
        try:
            counts_all[name] = await db[name].count_documents({})
            counts_mine[name] = await db[name].count_documents({"merchant_id": merchant_id})
        except Exception:  # noqa: BLE001 - a missing collection is simply zero
            counts_all[name] = 0
            counts_mine[name] = 0

    merchant = await find_one("merchants", {"merchant_id": merchant_id})
    policy = await find_one("policies", {"merchant_id": merchant_id})
    latest_event = await find_many("events", {"merchant_id": merchant_id}, sort=[("timestamp", -1)], limit=1)
    latest_state = await find_many(
        "merchant_states", {"merchant_id": merchant_id}, sort=[("computed_at", -1)], limit=1
    )

    return {
        "service": "business-brain",
        "version": "1.0.0",
        "now": utcnow(),
        "started_at": PROCESS_STARTED_AT,
        "uptime_seconds": round((utcnow() - PROCESS_STARTED_AT).total_seconds(), 1),
        "principal": principal,
        "merchant": merchant,
        "policy": policy,
        "dependencies": {
            "mongo": mongo,
            "redis": redis_state,
            "llm": {
                "provider": "gemini",
                "model": settings.gemini_model,
                "configured": bool(settings.gemini_api_key),
                "detail": "Copilot answers fall back to deterministic templates when unconfigured."
                if not settings.gemini_api_key
                else "Explanations are LLM-worded over structured tool evidence.",
            },
        },
        "config": {
            "mongo_db": settings.mongo_db,
            "cors_origins": settings.cors_origin_list,
            "jwt_expire_minutes": settings.jwt_expire_minutes,
            "seed_on_start": settings.seed_on_start,
            "seed_days": settings.seed_days,
        },
        "collections": [
            {"name": name, "documents": counts_all[name], "merchant_documents": counts_mine[name]}
            for name in COLLECTIONS
        ],
        "last_event_at": (latest_event[0].get("timestamp") if latest_event else None),
        "last_state_at": (latest_state[0].get("computed_at") if latest_state else None),
    }


@router.get("/analytics")
async def analytics(
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
    days: int = Query(30, ge=3, le=120),
) -> dict[str, Any]:
    return await analytics_bundle(principal["merchant_id"], days)


@router.get("/state-history")
async def history(
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
    limit: int = Query(60, ge=2, le=400),
) -> dict[str, Any]:
    return {"points": await state_history(principal["merchant_id"], limit)}


@router.get("/collections")
async def collections(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    db = get_db()
    rows = []
    for name in sorted(BROWSABLE):
        rows.append(
            {
                "name": name,
                "documents": await db[name].count_documents({"merchant_id": principal["merchant_id"]}),
                "sort_field": DEFAULT_SORT.get(name, "created_at"),
                "search_fields": SEARCH_FIELDS.get(name, []),
            }
        )
    return {"collections": rows}


@router.get("/collections/{name}")
async def browse(
    name: str,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
    q: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    sort_field: str | None = None,
    sort_dir: int = Query(-1, ge=-1, le=1),
) -> dict[str, Any]:
    if name not in BROWSABLE:
        raise HTTPException(status_code=404, detail=f"Collection '{name}' is not browsable")
    query: dict[str, Any] = {"merchant_id": principal["merchant_id"]}
    if q:
        fields = SEARCH_FIELDS.get(name) or ["status"]
        query["$or"] = [{field: {"$regex": q, "$options": "i"}} for field in fields]
    field = sort_field or DEFAULT_SORT.get(name, "created_at")
    total = await get_db()[name].count_documents(query)
    rows = await find_many(name, query, sort=[(field, sort_dir or -1)], limit=limit, skip=skip)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    return {
        "collection": name,
        "total": total,
        "limit": limit,
        "skip": skip,
        "sort_field": field,
        "sort_dir": sort_dir or -1,
        "columns": keys,
        "rows": rows,
    }


@router.get("/audit")
async def audit(
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    rows = await find_many(
        "audit_logs", {"merchant_id": principal["merchant_id"]}, sort=[("created_at", -1)], limit=limit
    )
    by_event = await aggregate_grouped(
        "audit_logs",
        [
            {"$match": {"merchant_id": principal["merchant_id"]}},
            {"$group": {"_id": "$event", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ],
    )
    return {
        "entries": rows,
        "by_event": [{"key": r["_id"] or "unknown", "count": int(r["count"])} for r in by_event],
    }


@router.get("/approvals")
async def approvals(
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
    status: str | None = None,
) -> dict[str, Any]:
    query: dict[str, Any] = {"merchant_id": principal["merchant_id"]}
    if status:
        query["status"] = status.upper()
    rows = await find_many("approvals", query, sort=[("created_at", -1)], limit=200)
    now = utcnow()
    for row in rows:
        expires = row.get("expires_at")
        row["expired"] = bool(expires and as_utc(expires) < now)
    return {"approvals": rows}


@router.get("/causal")
async def causal(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    from app.engines.causal import explain_cash_and_revenue

    return await explain_cash_and_revenue(principal["merchant_id"])


@router.get("/agents")
async def agents(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    from app.agents.orchestrator import AGENTS
    from app.engines.analytics import agent_leaderboard

    merchant_id = principal["merchant_id"]
    return {
        "registry": [{"agent_id": a.agent_id, "capabilities": a.capabilities} for a in AGENTS],
        "leaderboard": await agent_leaderboard(merchant_id),
        "runs": await find_many(
            "agent_runs", {"merchant_id": merchant_id}, sort=[("created_at", -1)], limit=40
        ),
        "circuit_breakers": await find_many(
            "circuit_breakers", {"merchant_id": merchant_id}, sort=[("updated_at", -1)], limit=40
        ),
    }


@router.get("/pipeline")
async def pipeline(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    """The decision trail: recommendation -> actions -> approvals -> outcomes."""
    merchant_id = principal["merchant_id"]
    recommendations = await find_many(
        "recommendations", {"merchant_id": merchant_id}, sort=[("created_at", -1)], limit=25
    )
    actions = await find_many("actions", {"merchant_id": merchant_id}, sort=[("created_at", -1)], limit=200)
    outcomes = await find_many("outcomes", {"merchant_id": merchant_id}, sort=[("created_at", -1)], limit=200)
    approvals_rows = await find_many("approvals", {"merchant_id": merchant_id}, sort=[("created_at", -1)], limit=200)

    by_action_outcome = {o.get("action_id"): o for o in outcomes}
    by_action_approval = {a.get("action_id"): a for a in approvals_rows}
    for action in actions:
        action["outcome"] = by_action_outcome.get(action.get("action_id"))
        action["approval"] = by_action_approval.get(action.get("action_id"))
    actions_by_rec: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        rec_id = action.get("recommendation_id")
        if rec_id:
            actions_by_rec.setdefault(rec_id, []).append(action)
    for rec in recommendations:
        rec["actions"] = actions_by_rec.get(rec.get("recommendation_id"), [])
    return {"recommendations": recommendations, "actions": actions}


@router.get("/self-test")
async def self_test_manifest(
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> dict[str, Any]:
    """The last stored run, so the console has something to show before you run it."""
    last = await find_many(
        "audit_logs",
        {"merchant_id": principal["merchant_id"], "event": "admin.self_test"},
        sort=[("created_at", -1)],
        limit=1,
    )
    return {"last_run": (last[0].get("detail") if last else None)}


@router.post("/self-test")
async def self_test(
    body: SelfTestRequest,
    principal: Annotated[dict[str, Any], Depends(authorized_merchant)],
) -> dict[str, Any]:
    from app.db import insert_one

    report = await run_self_test(principal["merchant_id"], principal, body.include_mutating)
    await insert_one(
        "audit_logs",
        {
            "merchant_id": principal["merchant_id"],
            "event": "admin.self_test",
            "actor": principal.get("user_id"),
            "created_at": utcnow(),
            "detail": {
                "summary": report["summary"],
                "include_mutating": report["include_mutating"],
                "duration_ms": report["duration_ms"],
                "ran_at": report["ran_at"],
                "failed_checks": [c["id"] for c in report["checks"] if c["status"] in {"failed", "errored"}],
            },
        },
    )
    return report
