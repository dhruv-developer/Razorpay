from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.agents.base import apply_trust_update
from app.db import find_one, get_db, insert_one, update_one
from app.engines.event_processor import ingest_raw
from app.engines.state_engine import get_current_state, recompute_merchant_state
from app.ids import new_id, new_token, new_trace_id
from app.safety.kernel import authorize_action
from app.safety.policy import evaluate_policy
from app.timeutil import as_utc, utcnow


def _reversibility(action_type: str) -> str:
    return {
        "observe": "read",
        "invoice.dunning.draft": "draft",
        "receivable.recover": "draft",
        "payment.retry": "reversible",
        "payout.delay": "reversible",
        "refund.create": "financial",
        "payout.create": "financial",
    }.get(action_type, "high_impact")


async def create_action(
    merchant_id: str,
    action: dict[str, Any],
    principal: dict[str, Any],
    recommendation_id: str | None = None,
) -> dict[str, Any]:
    action_type = action.get("type") or action.get("action_type")
    amount = int(action.get("amount") or action.get("amount_paise") or 0)
    policy = await evaluate_policy(merchant_id, action)
    action_id = action.get("action_id") or new_id("act")
    doc = {
        "action_id": action_id,
        "merchant_id": merchant_id,
        "agent_id": action.get("agent_id") or "human",
        "action_type": action_type,
        "input": action,
        "amount_paise": amount,
        "currency": "INR",
        "reason": action.get("reason"),
        "requires_approval": policy["requires_approval"],
        "policy_result": policy,
        "risk_level": action.get("risk_level") or ("high" if policy["action_level"] >= 3 else "medium"),
        "rollback_strategy": "none" if _reversibility(action_type or "") in {"financial", "high_impact"} else "revert_config",
        "reversibility": _reversibility(action_type or ""),
        "status": "PENDING_APPROVAL" if policy["requires_approval"] else "AUTHORIZED",
        "recommendation_id": recommendation_id,
        "created_at": utcnow(),
        "created_by": principal.get("user_id"),
        "trace_id": new_trace_id(),
        "expires_at": utcnow() + timedelta(hours=12),
    }
    await insert_one("actions", doc)
    if policy["requires_approval"]:
        token = new_token()
        await insert_one(
            "approvals",
            {
                "token": token,
                "action_id": action_id,
                "merchant_id": merchant_id,
                "amount_paise": amount,
                "action_type": action_type,
                "status": "PENDING",
                "created_at": utcnow(),
                "expires_at": doc["expires_at"],
            },
        )
        doc["approval_token"] = token
    await insert_one(
        "audit_logs",
        {
            "merchant_id": merchant_id,
            "action_id": action_id,
            "event": "action.created",
            "actor": principal.get("user_id"),
            "created_at": utcnow(),
            "detail": {"requires_approval": policy["requires_approval"]},
        },
    )
    return doc


async def decide_approval(token: str, approved: bool, principal: dict[str, Any]) -> dict[str, Any]:
    approval = await get_db().approvals.find_one({"token": token})
    if not approval:
        return {"ok": False, "detail": "Unknown approval token."}
    if approval["merchant_id"] != principal.get("merchant_id") and "platform_admin" not in principal.get("roles", []):
        return {"ok": False, "detail": "Caller cannot approve this merchant action."}
    if approval.get("status") != "PENDING":
        return {"ok": False, "detail": "Approval already resolved."}
    if approval.get("expires_at") and as_utc(approval["expires_at"]) < utcnow():
        await update_one("approvals", {"token": token}, {"$set": {"status": "EXPIRED"}})
        return {"ok": False, "detail": "Approval expired."}
    status = "APPROVED" if approved else "REJECTED"
    await update_one(
        "approvals",
        {"token": token},
        {"$set": {"status": status, "resolved_at": utcnow(), "resolved_by": principal.get("user_id")}},
    )
    await update_one(
        "actions",
        {"action_id": approval["action_id"]},
        {"$set": {"status": status, "approval_result": status, "approved_by": principal.get("user_id")}},
    )
    if approval.get("recommendation_id") or True:
        action = await find_one("actions", {"action_id": approval["action_id"]})
        if action and action.get("recommendation_id"):
            await update_one(
                "recommendations",
                {"recommendation_id": action["recommendation_id"]},
                {"$set": {"status": status}},
            )
    if approved:
        return await execute_action(approval["action_id"], principal)
    return {"ok": True, "status": "REJECTED", "action_id": approval["action_id"]}


async def execute_action(action_id: str, principal: dict[str, Any]) -> dict[str, Any]:
    action = await find_one("actions", {"action_id": action_id})
    if not action:
        return {"ok": False, "detail": "Unknown action."}
    merchant_id = action["merchant_id"]
    if action.get("requires_approval") and action.get("status") not in {"APPROVED", "AUTHORIZED"}:
        approval = await get_db().approvals.find_one({"action_id": action_id, "status": "APPROVED"})
        if not approval:
            return {"ok": False, "detail": "Action is not approved."}

    payload = {**(action.get("input") or {}), "action_id": action_id, "agent_id": action.get("agent_id")}
    gate = await authorize_action(principal, merchant_id, payload)
    if gate.get("duplicate"):
        # Idempotent replay: the money already moved on the first execution. Return
        # the recorded result instead of re-running the pipeline, which would
        # double-count the outcome and the agent trust update.
        return {
            "ok": True,
            "duplicate": True,
            "detail": "Action was already executed; returning the recorded result.",
            "action": action,
            "outcome": await find_one("outcomes", {"action_id": action_id}),
        }
    if not gate.get("ok"):
        await update_one("actions", {"action_id": action_id}, {"$set": {"status": "FAILED", "execution_result": gate}})
        return {"ok": False, **gate}

    before = await get_current_state(merchant_id)
    event_type, entity_id, event_payload = await _to_event(merchant_id, action)
    ingest = await ingest_raw(
        merchant_id,
        event_type,
        entity_id,
        event_payload,
        source="executor",
        event_id=f"evt_exec_{action_id}",
        trace_id=action.get("trace_id"),
    )
    remaining_invoices = (action.get("input") or {}).get("invoice_ids") or []
    if action["action_type"] == "receivable.recover" and len(remaining_invoices) > 1:
        for extra_id in remaining_invoices[1:]:
            inv = await find_one("invoices", {"merchant_id": merchant_id, "invoice_id": extra_id})
            if not inv or inv.get("status") == "paid":
                continue
            await ingest_raw(
                merchant_id,
                "invoice.paid",
                extra_id,
                {"amount": int(inv.get("amount_paise") or 0), "customer_id": inv.get("customer_id")},
                source="executor",
                trace_id=action.get("trace_id"),
            )
    await ingest_raw(
        merchant_id,
        "action.executed",
        action_id,
        {"action_type": action["action_type"], "amount": action.get("amount_paise")},
        source="executor",
        trace_id=action.get("trace_id"),
    )
    verified = await verify_action(action, ingest)
    after = await recompute_merchant_state(merchant_id)
    expected = int((action.get("input") or {}).get("amount") or action.get("amount_paise") or 0)
    if action["action_type"] == "payment.retry":
        actual = int(after.get("revenue_24h_paise") or 0) - int((before or {}).get("revenue_24h_paise") or 0)
    elif action["action_type"] == "receivable.recover":
        actual = int((before or {}).get("overdue_receivables_paise") or 0) - int(after.get("overdue_receivables_paise") or 0)
    else:
        actual = int(after.get("cash_paise") or 0) - int((before or {}).get("cash_paise") or 0)
    error = None
    if expected:
        error = abs(abs(actual) - expected) / expected
    outcome = {
        "outcome_id": new_id("out"),
        "merchant_id": merchant_id,
        "action_id": action_id,
        "agent_id": action.get("agent_id"),
        "recommendation_id": action.get("recommendation_id"),
        "expected_impact_paise": expected,
        "actual_impact_paise": actual,
        "prediction_error": error,
        "result": "positive" if verified["ok"] else "failed",
        "created_at": utcnow(),
    }
    await insert_one("outcomes", outcome)
    await apply_trust_update(merchant_id, action.get("agent_id") or "human", verified["ok"], error)
    status = "VERIFIED" if verified["ok"] else "FAILED"
    await update_one(
        "actions",
        {"action_id": action_id},
        {
            "$set": {
                "status": status,
                "execution_result": ingest,
                "verification": verified,
                "executed_at": utcnow(),
            }
        },
    )
    if action.get("recommendation_id"):
        await update_one(
            "recommendations",
            {"recommendation_id": action["recommendation_id"]},
            {"$set": {"status": status}},
        )
    await insert_one(
        "audit_logs",
        {
            "merchant_id": merchant_id,
            "action_id": action_id,
            "event": "action.verified" if verified["ok"] else "action.failed",
            "actor": principal.get("user_id"),
            "created_at": utcnow(),
            "detail": verified,
        },
    )
    return {"ok": verified["ok"], "action": await find_one("actions", {"action_id": action_id}), "outcome": outcome, "state": after}


async def _to_event(merchant_id: str, action: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    inp = action.get("input") or {}
    atype = action["action_type"]
    amount = action.get("amount_paise") or 0
    if atype == "payout.delay":
        payout_id = inp.get("payout_id")
        return (
            "payout.delayed",
            payout_id or action["action_id"],
            {
                "amount": amount,
                "duration_hours": inp.get("duration_hours") or 12,
                "vendor_id": inp.get("vendor_id"),
                "reason": action.get("reason"),
                "delay_until": utcnow() + timedelta(hours=int(inp.get("duration_hours") or 12)),
            },
        )
    if atype == "payout.create":
        return (
            "payout.completed",
            inp.get("payout_id") or action["action_id"],
            {"amount": amount, "vendor_id": inp.get("vendor_id"), "reason": action.get("reason")},
        )
    if atype == "receivable.recover":
        invoice_ids = inp.get("invoice_ids") or []
        remaining = list(invoice_ids[1:])
        if remaining:
            inp["invoice_ids_remaining"] = remaining
        if invoice_ids:
            first = invoice_ids[0]
            inv = await find_one("invoices", {"merchant_id": merchant_id, "invoice_id": first})
            return (
                "invoice.paid",
                first,
                {"amount": int(inv.get("amount_paise") or 0) if inv else amount, "customer_id": inv.get("customer_id") if inv else None},
            )
        return ("invoice.paid", action["action_id"], {"amount": amount})
    if atype == "payment.retry":
        payment_ids = inp.get("payment_ids") or []
        if payment_ids:
            original = await find_one("payments", {"merchant_id": merchant_id, "payment_id": payment_ids[0]})
            new_id_ = new_id("pay")
            return (
                "payment.captured",
                new_id_,
                {
                    "amount": int(original.get("amount_paise") or 0) if original else amount,
                    "method": (original or {}).get("method") or "upi",
                    "retry_of": payment_ids[0],
                    "customer_id": (original or {}).get("customer_id"),
                    "order_id": (original or {}).get("order_id"),
                    "channel": (original or {}).get("channel"),
                    "returning": (original or {}).get("returning"),
                },
            )
        return ("payment.captured", new_id("pay"), {"amount": amount, "method": "upi", "retry_of": "unknown"})
    if atype == "refund.create":
        return ("refund.processed", new_id("rfnd"), {"amount": amount, "payment_id": inp.get("payment_id")})
    return ("action.executed", action["action_id"], {"amount": amount, "type": atype})


async def verify_action(action: dict[str, Any], ingest: dict[str, Any]) -> dict[str, Any]:
    if ingest.get("status") == "duplicate":
        return {"ok": True, "detail": "Idempotent replay verified."}
    atype = action["action_type"]
    inp = action.get("input") or {}
    merchant_id = action["merchant_id"]
    if atype == "payout.delay":
        payout = await find_one("payouts", {"merchant_id": merchant_id, "payout_id": inp.get("payout_id") or action["action_id"]})
        ok = bool(payout and payout.get("status") == "delayed")
        return {"ok": ok, "entity": payout, "detail": "Payout status delayed." if ok else "Payout not delayed."}
    if atype == "receivable.recover":
        ids = inp.get("invoice_ids") or []
        if not ids:
            return {"ok": ingest.get("status") == "processed", "detail": "No invoice id to verify."}
        inv = await find_one("invoices", {"merchant_id": merchant_id, "invoice_id": ids[0]})
        ok = bool(inv and inv.get("status") == "paid")
        return {"ok": ok, "entity": inv, "detail": "Invoice marked paid." if ok else "Invoice not paid."}
    if atype == "payment.retry":
        retry = await find_one("payments", {"merchant_id": merchant_id, "retry_of": (inp.get("payment_ids") or [None])[0]})
        return {"ok": bool(retry and retry.get("status") == "captured"), "entity": retry, "detail": "Retry captured."}
    return {"ok": ingest.get("status") == "processed", "detail": "Event processed."}
