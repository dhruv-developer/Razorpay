from __future__ import annotations

from typing import Any

from app.db import get_db, update_one
from app.ids import new_id
from app.schemas.events import EventEnvelope
from app.timeutil import as_utc, utcnow


async def link(
    merchant_id: str,
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    rel: str,
    extra: dict[str, Any] | None = None,
) -> None:
    await update_one(
        "relationships",
        {
            "merchant_id": merchant_id,
            "from_type": from_type,
            "from_id": from_id,
            "to_type": to_type,
            "to_id": to_id,
            "rel": rel,
        },
        {
            "$set": {
                "merchant_id": merchant_id,
                "from_type": from_type,
                "from_id": from_id,
                "to_type": to_type,
                "to_id": to_id,
                "rel": rel,
                "updated_at": utcnow(),
                **(extra or {}),
            },
            "$setOnInsert": {"created_at": utcnow()},
        },
        upsert=True,
    )


async def _ensure_cash_account(merchant_id: str) -> None:
    db = get_db()
    existing = await db.cash_accounts.find_one({"merchant_id": merchant_id})
    if existing:
        return
    await db.cash_accounts.insert_one(
        {
            "merchant_id": merchant_id,
            "account_id": new_id("cash"),
            "currency": "INR",
            "balance_paise": 0,
            "updated_at": utcnow(),
        }
    )


async def adjust_cash(merchant_id: str, delta_paise: int, reason: str, ref: str) -> None:
    await _ensure_cash_account(merchant_id)
    await update_one(
        "cash_accounts",
        {"merchant_id": merchant_id},
        {
            "$inc": {"balance_paise": int(delta_paise)},
            "$set": {"updated_at": utcnow(), "last_reason": reason, "last_ref": ref},
        },
        upsert=True,
    )


def _payload_amount(payload: dict[str, Any]) -> int:
    return int(payload.get("amount") or payload.get("amount_paise") or 0)


def _method(payload: dict[str, Any]) -> str:
    return str(payload.get("method") or payload.get("payment_method") or "unknown")


async def _upsert_customer(merchant_id: str, customer_id: str, payload: dict[str, Any], ts) -> None:
    if not customer_id:
        return
    segment = payload.get("segment") or "standard"
    returning = bool(payload.get("returning") or payload.get("is_returning"))
    channel = payload.get("channel") or payload.get("device") or "unknown"
    fields = {
        "merchant_id": merchant_id,
        "customer_id": customer_id,
        "segment": segment,
        "channel": channel,
        "updated_at": ts,
    }
    if returning:
        fields["returning"] = True
    await update_one(
        "customers",
        {"merchant_id": merchant_id, "customer_id": customer_id},
        {
            "$set": fields,
            "$setOnInsert": {"created_at": ts, "order_count": 0},
            "$inc": {"seen_count": 1},
        },
        upsert=True,
    )
    await link(merchant_id, "merchant", merchant_id, "customer", customer_id, "has_customer")


async def handle_customer(envelope: EventEnvelope) -> None:
    ts = as_utc(envelope.timestamp)
    await _upsert_customer(envelope.merchant_id, envelope.entity_id, envelope.payload, ts)
    if envelope.event_type == "customer.returned":
        await update_one(
            "customers",
            {"merchant_id": envelope.merchant_id, "customer_id": envelope.entity_id},
            {"$set": {"returning": True, "last_returned_at": ts}},
        )


async def handle_order(envelope: EventEnvelope) -> None:
    ts = as_utc(envelope.timestamp)
    p = envelope.payload
    customer_id = p.get("customer_id")
    product_id = p.get("product_id")
    status = {
        "order.created": "created",
        "order.paid": "paid",
        "order.cancelled": "cancelled",
    }.get(envelope.event_type, p.get("status") or "created")
    await update_one(
        "orders",
        {"merchant_id": envelope.merchant_id, "order_id": envelope.entity_id},
        {
            "$set": {
                "merchant_id": envelope.merchant_id,
                "order_id": envelope.entity_id,
                "customer_id": customer_id,
                "product_id": product_id,
                "amount_paise": _payload_amount(p),
                "currency": p.get("currency", "INR"),
                "channel": p.get("channel") or p.get("device") or "unknown",
                "status": status,
                "updated_at": ts,
            },
            "$setOnInsert": {"created_at": ts},
        },
        upsert=True,
    )
    if customer_id:
        await _upsert_customer(envelope.merchant_id, customer_id, p, ts)
        await link(envelope.merchant_id, "customer", customer_id, "order", envelope.entity_id, "placed")
        if envelope.event_type == "order.created":
            await update_one(
                "customers",
                {"merchant_id": envelope.merchant_id, "customer_id": customer_id},
                {"$inc": {"order_count": 1}},
            )
    if product_id:
        await update_one(
            "products",
            {"merchant_id": envelope.merchant_id, "product_id": product_id},
            {
                "$set": {
                    "merchant_id": envelope.merchant_id,
                    "product_id": product_id,
                    "name": p.get("product_name") or product_id,
                    "updated_at": ts,
                },
                "$setOnInsert": {"created_at": ts},
                "$inc": {"order_count": 1 if envelope.event_type == "order.created" else 0},
            },
            upsert=True,
        )
        await link(envelope.merchant_id, "product", product_id, "order", envelope.entity_id, "sold_in")


async def handle_payment(envelope: EventEnvelope) -> None:
    ts = as_utc(envelope.timestamp)
    p = envelope.payload
    status = {
        "payment.authorized": "authorized",
        "payment.captured": "captured",
        "payment.failed": "failed",
        "payment.refunded": "refunded",
        "subscription.payment_failed": "failed",
        "subscription.recovered": "captured",
    }.get(envelope.event_type, p.get("status") or "unknown")
    order_id = p.get("order_id")
    customer_id = p.get("customer_id")
    method = _method(p)
    await update_one(
        "payments",
        {"merchant_id": envelope.merchant_id, "payment_id": envelope.entity_id},
        {
            "$set": {
                "merchant_id": envelope.merchant_id,
                "payment_id": envelope.entity_id,
                "order_id": order_id,
                "customer_id": customer_id,
                "amount_paise": _payload_amount(p),
                "currency": p.get("currency", "INR"),
                "method": method,
                "status": status,
                "failure_code": p.get("failure_code"),
                "channel": p.get("channel") or p.get("device") or "unknown",
                "returning": bool(p.get("returning")),
                "retry_of": p.get("retry_of"),
                "subscription_id": p.get("subscription_id"),
                "updated_at": ts,
            },
            "$setOnInsert": {"created_at": ts},
        },
        upsert=True,
    )
    if customer_id:
        await _upsert_customer(envelope.merchant_id, customer_id, p, ts)
        await link(envelope.merchant_id, "customer", customer_id, "payment", envelope.entity_id, "paid_with")
    if order_id:
        await link(envelope.merchant_id, "order", order_id, "payment", envelope.entity_id, "settled_by")
        if status == "captured":
            await update_one(
                "orders",
                {"merchant_id": envelope.merchant_id, "order_id": order_id},
                {"$set": {"status": "paid", "updated_at": ts}},
            )
        elif status == "failed" and envelope.event_type == "payment.failed":
            await update_one(
                "orders",
                {"merchant_id": envelope.merchant_id, "order_id": order_id},
                {"$set": {"last_payment_failed_at": ts, "updated_at": ts}},
            )
    if envelope.event_type == "subscription.payment_failed" or envelope.event_type == "subscription.recovered":
        sub_id = p.get("subscription_id") or envelope.entity_id
        await update_one(
            "subscriptions",
            {"merchant_id": envelope.merchant_id, "subscription_id": sub_id},
            {
                "$set": {
                    "merchant_id": envelope.merchant_id,
                    "subscription_id": sub_id,
                    "customer_id": customer_id,
                    "status": "active" if envelope.event_type == "subscription.recovered" else "past_due",
                    "updated_at": ts,
                },
                "$setOnInsert": {"created_at": ts, "amount_paise": _payload_amount(p)},
            },
            upsert=True,
        )


async def handle_refund(envelope: EventEnvelope) -> None:
    ts = as_utc(envelope.timestamp)
    p = envelope.payload
    status = "processed" if envelope.event_type in {"refund.processed", "payment.refunded"} else "pending"
    payment_id = p.get("payment_id") or envelope.entity_id
    amount = _payload_amount(p)
    await update_one(
        "refunds",
        {"merchant_id": envelope.merchant_id, "refund_id": envelope.entity_id},
        {
            "$set": {
                "merchant_id": envelope.merchant_id,
                "refund_id": envelope.entity_id,
                "payment_id": payment_id,
                "amount_paise": amount,
                "status": status,
                "reason": p.get("reason"),
                "updated_at": ts,
            },
            "$setOnInsert": {"created_at": ts},
        },
        upsert=True,
    )
    if status == "processed" and not p.get("already_in_cash"):
        await adjust_cash(envelope.merchant_id, -amount, "refund.processed", envelope.entity_id)
        await update_one(
            "payments",
            {"merchant_id": envelope.merchant_id, "payment_id": payment_id},
            {"$set": {"status": "refunded", "updated_at": ts}},
        )


async def handle_settlement(envelope: EventEnvelope) -> None:
    ts = as_utc(envelope.timestamp)
    p = envelope.payload
    status = {
        "settlement.created": "pending",
        "settlement.delayed": "delayed",
        "settlement.processed": "processed",
    }.get(envelope.event_type, p.get("status") or "pending")
    amount = _payload_amount(p)
    existing = await get_db().settlements.find_one(
        {"merchant_id": envelope.merchant_id, "settlement_id": envelope.entity_id}
    )
    prev_status = existing.get("status") if existing else None
    await update_one(
        "settlements",
        {"merchant_id": envelope.merchant_id, "settlement_id": envelope.entity_id},
        {
            "$set": {
                "merchant_id": envelope.merchant_id,
                "settlement_id": envelope.entity_id,
                "amount_paise": amount or (existing.get("amount_paise") if existing else 0),
                "status": status,
                "delay_hours": p.get("delay_hours"),
                "updated_at": ts,
            },
            "$setOnInsert": {"created_at": ts},
        },
        upsert=True,
    )
    credited = amount or (existing.get("amount_paise") if existing else 0)
    already_in_cash = bool(p.get("already_in_cash"))
    if status == "processed" and prev_status != "processed" and not already_in_cash:
        await adjust_cash(envelope.merchant_id, int(credited), "settlement.processed", envelope.entity_id)
    await link(envelope.merchant_id, "merchant", envelope.merchant_id, "settlement", envelope.entity_id, "has_settlement")


async def handle_payout(envelope: EventEnvelope) -> None:
    ts = as_utc(envelope.timestamp)
    p = envelope.payload
    status = {
        "payout.created": "scheduled",
        "payout.completed": "completed",
        "payout.delayed": "delayed",
    }.get(envelope.event_type, p.get("status") or "scheduled")
    amount = _payload_amount(p)
    vendor_id = p.get("vendor_id")
    existing = await get_db().payouts.find_one(
        {"merchant_id": envelope.merchant_id, "payout_id": envelope.entity_id}
    )
    prev_status = existing.get("status") if existing else None
    delay_until = p.get("delay_until")
    await update_one(
        "payouts",
        {"merchant_id": envelope.merchant_id, "payout_id": envelope.entity_id},
        {
            "$set": {
                "merchant_id": envelope.merchant_id,
                "payout_id": envelope.entity_id,
                "amount_paise": amount or (existing.get("amount_paise") if existing else 0),
                "vendor_id": vendor_id,
                "status": status,
                "reason": p.get("reason"),
                "delay_hours": p.get("duration_hours") or p.get("delay_hours"),
                "delay_until": delay_until,
                "updated_at": ts,
            },
            "$setOnInsert": {"created_at": ts},
        },
        upsert=True,
    )
    paid = amount or (existing.get("amount_paise") if existing else 0)
    if status == "completed" and prev_status != "completed" and not p.get("already_in_cash"):
        await adjust_cash(envelope.merchant_id, -int(paid), "payout.completed", envelope.entity_id)
    if vendor_id:
        await update_one(
            "vendors",
            {"merchant_id": envelope.merchant_id, "vendor_id": vendor_id},
            {
                "$set": {
                    "merchant_id": envelope.merchant_id,
                    "vendor_id": vendor_id,
                    "name": p.get("vendor_name") or vendor_id,
                    "updated_at": ts,
                },
                "$setOnInsert": {"created_at": ts},
            },
            upsert=True,
        )
        await link(envelope.merchant_id, "payout", envelope.entity_id, "vendor", vendor_id, "paid_to")


async def handle_invoice(envelope: EventEnvelope) -> None:
    ts = as_utc(envelope.timestamp)
    p = envelope.payload
    status = {
        "invoice.created": "open",
        "invoice.paid": "paid",
        "invoice.overdue": "overdue",
    }.get(envelope.event_type, p.get("status") or "open")
    customer_id = p.get("customer_id")
    amount = _payload_amount(p)
    existing = await get_db().invoices.find_one(
        {"merchant_id": envelope.merchant_id, "invoice_id": envelope.entity_id}
    )
    await update_one(
        "invoices",
        {"merchant_id": envelope.merchant_id, "invoice_id": envelope.entity_id},
        {
            "$set": {
                "merchant_id": envelope.merchant_id,
                "invoice_id": envelope.entity_id,
                "customer_id": customer_id,
                "amount_paise": amount or (existing.get("amount_paise") if existing else 0),
                "status": status,
                "due_at": p.get("due_at"),
                "updated_at": ts,
            },
            "$setOnInsert": {"created_at": ts},
        },
        upsert=True,
    )
    if customer_id:
        await link(envelope.merchant_id, "invoice", envelope.entity_id, "customer", customer_id, "billed_to")
    if envelope.event_type == "invoice.paid" and not p.get("already_in_cash"):
        credited = amount or (existing.get("amount_paise") if existing else 0)
        await adjust_cash(envelope.merchant_id, int(credited), "invoice.paid", envelope.entity_id)


async def handle_dispute(envelope: EventEnvelope) -> None:
    ts = as_utc(envelope.timestamp)
    p = envelope.payload
    status = "open" if envelope.event_type == "dispute.created" else "resolved"
    payment_id = p.get("payment_id")
    await update_one(
        "disputes",
        {"merchant_id": envelope.merchant_id, "dispute_id": envelope.entity_id},
        {
            "$set": {
                "merchant_id": envelope.merchant_id,
                "dispute_id": envelope.entity_id,
                "payment_id": payment_id,
                "amount_paise": _payload_amount(p),
                "status": status,
                "reason": p.get("reason"),
                "updated_at": ts,
            },
            "$setOnInsert": {"created_at": ts},
        },
        upsert=True,
    )
    if payment_id:
        await link(envelope.merchant_id, "dispute", envelope.entity_id, "payment", payment_id, "disputes")


async def handle_payroll(envelope: EventEnvelope) -> None:
    ts = as_utc(envelope.timestamp)
    p = envelope.payload
    await update_one(
        "employees",
        {"merchant_id": envelope.merchant_id, "employee_id": p.get("employee_id") or envelope.entity_id},
        {
            "$set": {
                "merchant_id": envelope.merchant_id,
                "employee_id": p.get("employee_id") or envelope.entity_id,
                "scheduled_payroll_paise": _payload_amount(p),
                "scheduled_at": p.get("scheduled_at") or ts,
                "updated_at": ts,
            },
            "$setOnInsert": {"created_at": ts},
        },
        upsert=True,
    )


async def handle_cash_adjusted(envelope: EventEnvelope) -> None:
    await adjust_cash(
        envelope.merchant_id,
        int(envelope.payload.get("delta_paise") or _payload_amount(envelope.payload)),
        envelope.payload.get("reason") or "cash.adjusted",
        envelope.entity_id,
    )


async def handle_action_lifecycle(envelope: EventEnvelope) -> None:
    # Downstream verification events; ledger is owned by the executor.
    return


HANDLERS = {
    "customer.created": handle_customer,
    "customer.returned": handle_customer,
    "order.created": handle_order,
    "order.paid": handle_order,
    "order.cancelled": handle_order,
    "payment.failed": handle_payment,
    "payment.captured": handle_payment,
    "payment.authorized": handle_payment,
    "payment.refunded": handle_refund,
    "subscription.payment_failed": handle_payment,
    "subscription.recovered": handle_payment,
    "refund.created": handle_refund,
    "refund.processed": handle_refund,
    "settlement.created": handle_settlement,
    "settlement.delayed": handle_settlement,
    "settlement.processed": handle_settlement,
    "payout.created": handle_payout,
    "payout.completed": handle_payout,
    "payout.delayed": handle_payout,
    "invoice.created": handle_invoice,
    "invoice.paid": handle_invoice,
    "invoice.overdue": handle_invoice,
    "dispute.created": handle_dispute,
    "dispute.resolved": handle_dispute,
    "payroll.scheduled": handle_payroll,
    "cash.adjusted": handle_cash_adjusted,
    "action.executed": handle_action_lifecycle,
    "action.verified": handle_action_lifecycle,
}


async def apply_entity_update(envelope: EventEnvelope) -> None:
    await _ensure_cash_account(envelope.merchant_id)
    handler = HANDLERS.get(envelope.event_type)
    if handler:
        await handler(envelope)
