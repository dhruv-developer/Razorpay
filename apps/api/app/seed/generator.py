from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from app.config import get_settings
from app.db import find_one, insert_one
from app.engines.decision import run_brain_cycle
from app.engines.event_processor import finalize_merchant, ingest_raw
from app.engines.memory import seed_structured_memories
from app.ids import new_id
from app.money import paise
from app.security import hash_password
from app.timeutil import utcnow


async def seed_if_needed() -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.seed_on_start:
        return None
    existing = await find_one("users", {"email": settings.seed_email.lower()})
    if existing:
        return {"status": "exists", "merchant_id": existing["merchant_id"]}
    return await seed_merchant()


async def seed_merchant() -> dict[str, Any]:
    settings = get_settings()
    rng = random.Random(42)
    now = utcnow()
    tenant_id = new_id("ten")
    merchant_id = new_id("merch")
    user_id = new_id("user")
    reserve = paise(20_00_000)  # ₹20L merchant-configured reserve
    policy = {
        "merchant_id": merchant_id,
        "cash_reserve_minimum_paise": reserve,
        "automatic_refund_maximum_paise": paise(5_000),
        "payout_automatic_limit_paise": paise(5_00_000),
        "autonomy_level": "recommend",
        "weights": {"growth": 0.25, "cash": 0.55, "risk": 0.2},
        "created_at": now,
    }
    await insert_one("tenants", {"tenant_id": tenant_id, "name": settings.seed_merchant_name, "created_at": now})
    await insert_one(
        "merchants",
        {
            "merchant_id": merchant_id,
            "tenant_id": tenant_id,
            "name": settings.seed_merchant_name,
            "industry": "electronics",
            "active": True,
            "created_at": now,
        },
    )
    await insert_one(
        "users",
        {
            "user_id": user_id,
            "email": settings.seed_email.lower(),
            "password_hash": hash_password(settings.seed_password),
            "merchant_id": merchant_id,
            "tenant_id": tenant_id,
            "roles": ["merchant_admin"],
            "active": True,
            "created_at": now,
        },
    )
    await insert_one("policies", policy)
    await seed_structured_memories(merchant_id, settings.seed_merchant_name, policy)

    vendors = [
        {"vendor_id": new_id("vnd"), "name": "Foxconn Components"},
        {"vendor_id": new_id("vnd"), "name": "Delhivery Logistics"},
        {"vendor_id": new_id("vnd"), "name": "AWS India"},
    ]
    products = [new_id("prod") for _ in range(8)]
    customers = []
    for i in range(180):
        cid = new_id("cust")
        customers.append(
            {
                "customer_id": cid,
                "segment": "premium" if i < 20 else "standard",
                "channel": "mobile" if i % 3 else "web",
            }
        )
        await ingest_raw(
            merchant_id,
            "customer.created",
            cid,
            {"segment": customers[-1]["segment"], "channel": customers[-1]["channel"]},
            source="seed",
            timestamp=now - timedelta(days=settings.seed_days, hours=i % 20),
            run_downstream=False,
        )

    opening_cash = paise(22_00_000)
    await ingest_raw(
        merchant_id,
        "cash.adjusted",
        new_id("cash"),
        {"delta_paise": opening_cash, "reason": "opening_balance"},
        source="seed",
        timestamp=now - timedelta(days=settings.seed_days),
        run_downstream=False,
    )

    daily_captured: list[int] = []
    for day in range(settings.seed_days, 0, -1):
        day_start = now - timedelta(days=day)
        spike = day <= 1
        n_orders = rng.randint(36, 52)
        captured_today = 0
        failed_amount = 0
        methods = ["upi", "upi", "upi", "card", "netbanking", "wallet"]
        for i in range(n_orders):
            customer = rng.choice(customers)
            returning = rng.random() < (0.62 if day < 10 else 0.48)
            ts = day_start + timedelta(hours=rng.randint(8, 21), minutes=rng.randint(0, 59))
            amount = paise(rng.randint(8_000, 55_000))
            method = rng.choice(methods)
            order_id = new_id("ord")
            payment_id = new_id("pay")
            await ingest_raw(
                merchant_id,
                "order.created",
                order_id,
                {
                    "amount": amount,
                    "customer_id": customer["customer_id"],
                    "product_id": rng.choice(products),
                    "channel": customer["channel"],
                    "returning": returning,
                    "segment": customer["segment"],
                    "currency": "INR",
                },
                source="seed",
                timestamp=ts,
                run_downstream=False,
            )
            fail_p = 0.04
            if method == "upi":
                fail_p = 0.035
            if spike and method == "upi" and returning and customer["channel"] == "mobile":
                fail_p = 0.22
            elif spike and method == "upi":
                fail_p = 0.11
            failed = rng.random() < fail_p
            if failed:
                await ingest_raw(
                    merchant_id,
                    "payment.failed",
                    payment_id,
                    {
                        "amount": amount,
                        "currency": "INR",
                        "method": method,
                        "failure_code": "TIMEOUT" if method == "upi" else "GATEWAY_ERROR",
                        "order_id": order_id,
                        "customer_id": customer["customer_id"],
                        "channel": customer["channel"],
                        "returning": returning,
                    },
                    source="seed",
                    timestamp=ts + timedelta(seconds=8),
                    run_downstream=False,
                )
                failed_amount += amount
            else:
                await ingest_raw(
                    merchant_id,
                    "payment.captured",
                    payment_id,
                    {
                        "amount": amount,
                        "currency": "INR",
                        "method": method,
                        "order_id": order_id,
                        "customer_id": customer["customer_id"],
                        "channel": customer["channel"],
                        "returning": returning,
                    },
                    source="seed",
                    timestamp=ts + timedelta(seconds=6),
                    run_downstream=False,
                )
                captured_today += amount
                if rng.random() < 0.018:
                    await ingest_raw(
                        merchant_id,
                        "refund.processed",
                        new_id("rfnd"),
                        {"amount": amount, "payment_id": payment_id, "reason": "customer_request", "already_in_cash": True},
                        source="seed",
                        timestamp=ts + timedelta(hours=6),
                        run_downstream=False,
                    )
                    captured_today -= amount
        daily_captured.append(captured_today)
        # T+1 settlement: older days processed, last 2 days delayed/pending
        settlement_id = new_id("setl")
        settle_ts = day_start + timedelta(hours=23)
        await ingest_raw(
            merchant_id,
            "settlement.created",
            settlement_id,
            {"amount": captured_today, "currency": "INR"},
            source="seed",
            timestamp=settle_ts,
            run_downstream=False,
        )
        if day >= 3:
            await ingest_raw(
                merchant_id,
                "settlement.processed",
                settlement_id,
                {"amount": captured_today, "currency": "INR", "already_in_cash": True},
                source="seed",
                timestamp=settle_ts + timedelta(hours=18),
                run_downstream=False,
            )
        elif day == 2:
            await ingest_raw(
                merchant_id,
                "settlement.delayed",
                settlement_id,
                {"amount": captured_today, "currency": "INR", "delay_hours": 16},
                source="seed",
                timestamp=settle_ts + timedelta(hours=12),
                run_downstream=False,
            )
        if rng.random() < 0.08:
            await ingest_raw(
                merchant_id,
                "dispute.created",
                new_id("disp"),
                {"amount": paise(rng.randint(4_000, 18_000)), "reason": "chargeback"},
                source="seed",
                timestamp=day_start + timedelta(hours=20),
                run_downstream=False,
            )

    # Historical completed payouts plus upcoming obligations
    for i, vendor in enumerate(vendors):
        hist_id = new_id("pout")
        hist_amt = paise(rng.randint(1_20_000, 3_50_000))
        ts = now - timedelta(days=10 - i, hours=4)
        await ingest_raw(
            merchant_id,
            "payout.created",
            hist_id,
            {"amount": hist_amt, "vendor_id": vendor["vendor_id"], "vendor_name": vendor["name"]},
            source="seed",
            timestamp=ts,
            run_downstream=False,
        )
        await ingest_raw(
            merchant_id,
            "payout.completed",
            hist_id,
            {"amount": hist_amt, "vendor_id": vendor["vendor_id"], "already_in_cash": True},
            source="seed",
            timestamp=ts + timedelta(hours=2),
            run_downstream=False,
        )

    upcoming = [
        (vendors[0], paise(7_00_000)),
        (vendors[1], paise(3_20_000)),
        (vendors[2], paise(1_80_000)),
    ]
    for vendor, amount in upcoming:
        await ingest_raw(
            merchant_id,
            "payout.created",
            new_id("pout"),
            {
                "amount": amount,
                "vendor_id": vendor["vendor_id"],
                "vendor_name": vendor["name"],
                "reason": "scheduled_vendor_obligation",
            },
            source="seed",
            timestamp=now - timedelta(hours=6),
            run_downstream=False,
        )

    for i in range(7):
        cust = rng.choice(customers)
        inv_id = new_id("inv")
        amount = paise(rng.randint(40_000, 1_20_000))
        created = now - timedelta(days=18 - i)
        await ingest_raw(
            merchant_id,
            "invoice.created",
            inv_id,
            {"amount": amount, "customer_id": cust["customer_id"], "due_at": created + timedelta(days=7)},
            source="seed",
            timestamp=created,
            run_downstream=False,
        )
        if i < 3:
            await ingest_raw(
                merchant_id,
                "invoice.paid",
                inv_id,
                {"amount": amount, "customer_id": cust["customer_id"], "already_in_cash": True},
                source="seed",
                timestamp=created + timedelta(days=5),
                run_downstream=False,
            )
        else:
            await ingest_raw(
                merchant_id,
                "invoice.overdue",
                inv_id,
                {"amount": amount, "customer_id": cust["customer_id"]},
                source="seed",
                timestamp=created + timedelta(days=10),
                run_downstream=False,
            )

    await ingest_raw(
        merchant_id,
        "payroll.scheduled",
        new_id("prl"),
        {"amount": paise(2_40_000), "scheduled_at": now + timedelta(days=3)},
        source="seed",
        timestamp=now - timedelta(hours=2),
        run_downstream=False,
    )

    await finalize_merchant(merchant_id)
    cycle = await run_brain_cycle(merchant_id)
    return {
        "status": "seeded",
        "merchant_id": merchant_id,
        "email": settings.seed_email,
        "cycle": {
            "label": (cycle.get("state") or {}).get("label"),
            "cash_paise": (cycle.get("state") or {}).get("cash_paise"),
            "reserve_breach_probability": (cycle.get("state") or {}).get("reserve_breach_probability"),
        },
    }
