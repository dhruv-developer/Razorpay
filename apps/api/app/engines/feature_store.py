from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.db import get_db, replace_one
from app.engines.aggregates import count_docs, sum_field
from app.timeutil import utcnow

WINDOWS: dict[str, timedelta] = {
    "5m": timedelta(minutes=5),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _rate(success: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(success / total, 6)


async def _window_payment_stats(merchant_id: str, since: datetime) -> dict[str, Any]:
    captured = await count_docs("payments", merchant_id, {"status": "captured", "created_at": {"$gte": since}})
    failed = await count_docs("payments", merchant_id, {"status": "failed", "created_at": {"$gte": since}})
    refunded = await count_docs("payments", merchant_id, {"status": "refunded", "created_at": {"$gte": since}})
    total = captured + failed + refunded
    gmv = await sum_field("payments", merchant_id, {"status": "captured", "created_at": {"$gte": since}})
    failed_gmv = await sum_field("payments", merchant_id, {"status": "failed", "created_at": {"$gte": since}})
    refund_gmv = await sum_field("refunds", merchant_id, {"created_at": {"$gte": since}})
    upi_failed = await count_docs(
        "payments",
        merchant_id,
        {"status": "failed", "method": "upi", "created_at": {"$gte": since}},
    )
    upi_total = await count_docs("payments", merchant_id, {"method": "upi", "created_at": {"$gte": since}})
    returning_failed = await count_docs(
        "payments",
        merchant_id,
        {"status": "failed", "returning": True, "created_at": {"$gte": since}},
    )
    mobile_failed = await count_docs(
        "payments",
        merchant_id,
        {"status": "failed", "channel": "mobile", "created_at": {"$gte": since}},
    )
    timeout_failed = await count_docs(
        "payments",
        merchant_id,
        {"status": "failed", "failure_code": "TIMEOUT", "created_at": {"$gte": since}},
    )
    aov = int(gmv / captured) if captured else 0
    return {
        "captured": captured,
        "failed": failed,
        "refunded": refunded,
        "total": total,
        "gmv_paise": gmv,
        "failed_gmv_paise": failed_gmv,
        "refund_gmv_paise": refund_gmv,
        "success_rate": _rate(captured, total),
        "failure_rate": _rate(failed, total),
        "refund_rate": _rate(refunded, captured + refunded),
        "upi_failure_rate": _rate(upi_failed, upi_total),
        "returning_failed": returning_failed,
        "mobile_failed": mobile_failed,
        "timeout_failed": timeout_failed,
        "average_order_value_paise": aov,
        "failure_velocity": failed,
    }


async def backfill_daily_series(merchant_id: str, days: int = 30) -> None:
    """Persist actual daily success/failure/GMV so baselines are not a single snapshot."""
    now = utcnow()
    db = get_db()
    for day in range(days, 0, -1):
        start = (now - timedelta(days=day)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        stats = await _window_payment_stats_range(merchant_id, start, end)
        for name in ("success_rate", "failure_rate", "gmv_paise"):
            await db.feature_series.update_one(
                {"merchant_id": merchant_id, "name": name, "window": "24h", "bucket": start},
                {
                    "$set": {
                        "merchant_id": merchant_id,
                        "name": name,
                        "window": "24h",
                        "bucket": start,
                        "value": stats[name],
                        "computed_at": now,
                    }
                },
                upsert=True,
            )


async def _window_payment_stats_range(merchant_id: str, start, end) -> dict[str, Any]:
    captured = await count_docs("payments", merchant_id, {"status": "captured", "created_at": {"$gte": start, "$lt": end}})
    failed = await count_docs("payments", merchant_id, {"status": "failed", "created_at": {"$gte": start, "$lt": end}})
    refunded = await count_docs("payments", merchant_id, {"status": "refunded", "created_at": {"$gte": start, "$lt": end}})
    total = captured + failed + refunded
    gmv = await sum_field("payments", merchant_id, {"status": "captured", "created_at": {"$gte": start, "$lt": end}})
    return {
        "success_rate": _rate(captured, total),
        "failure_rate": _rate(failed, total),
        "gmv_paise": gmv,
    }


async def recompute_features(merchant_id: str) -> dict[str, Any]:
    now = utcnow()
    db = get_db()
    snapshot: dict[str, Any] = {}
    for window, delta in WINDOWS.items():
        since = now - delta
        stats = await _window_payment_stats(merchant_id, since)
        for name, value in stats.items():
            await replace_one(
                "features",
                {"merchant_id": merchant_id, "name": name, "window": window},
                {
                    "merchant_id": merchant_id,
                    "name": name,
                    "window": window,
                    "value": value,
                    "computed_at": now,
                },
                upsert=True,
            )
            snapshot[f"{name}_{window}"] = value

        hour_bucket = now.replace(minute=0, second=0, microsecond=0)
        await db.feature_series.update_one(
            {"merchant_id": merchant_id, "name": "success_rate", "window": window, "bucket": hour_bucket},
            {
                "$set": {
                    "merchant_id": merchant_id,
                    "name": "success_rate",
                    "window": window,
                    "bucket": hour_bucket,
                    "value": stats["success_rate"],
                    "computed_at": now,
                }
            },
            upsert=True,
        )
        await db.feature_series.update_one(
            {"merchant_id": merchant_id, "name": "failure_rate", "window": window, "bucket": hour_bucket},
            {
                "$set": {
                    "merchant_id": merchant_id,
                    "name": "failure_rate",
                    "window": window,
                    "bucket": hour_bucket,
                    "value": stats["failure_rate"],
                    "computed_at": now,
                }
            },
            upsert=True,
        )
        await db.feature_series.update_one(
            {"merchant_id": merchant_id, "name": "gmv_paise", "window": window, "bucket": hour_bucket},
            {
                "$set": {
                    "merchant_id": merchant_id,
                    "name": "gmv_paise",
                    "window": window,
                    "bucket": hour_bucket,
                    "value": stats["gmv_paise"],
                    "computed_at": now,
                }
            },
            upsert=True,
        )

    extra = {
        "receivable_age_overdue_paise": await sum_field("invoices", merchant_id, {"status": "overdue"}),
        "pending_settlement_paise": await sum_field(
            "settlements", merchant_id, {"status": {"$in": ["pending", "delayed"]}}
        ),
        "scheduled_payout_paise": await sum_field(
            "payouts", merchant_id, {"status": {"$in": ["scheduled", "delayed"]}}
        ),
        "open_dispute_paise": await sum_field("disputes", merchant_id, {"status": "open"}),
        "pending_refund_paise": await sum_field("refunds", merchant_id, {"status": "pending"}),
    }
    for name, value in extra.items():
        await replace_one(
            "features",
            {"merchant_id": merchant_id, "name": name, "window": "current"},
            {
                "merchant_id": merchant_id,
                "name": name,
                "window": "current",
                "value": value,
                "computed_at": now,
            },
            upsert=True,
        )
        snapshot[name] = value
    return snapshot


async def get_features(merchant_id: str) -> dict[str, Any]:
    rows = await get_db().features.find({"merchant_id": merchant_id}).to_list(500)
    out: dict[str, Any] = {}
    for row in rows:
        key = f"{row['name']}_{row['window']}"
        out[key] = row.get("value")
    return out


async def get_feature(merchant_id: str, name: str, window: str) -> float | int | None:
    row = await get_db().features.find_one({"merchant_id": merchant_id, "name": name, "window": window})
    if not row:
        return None
    return row.get("value")


async def feature_history(merchant_id: str, name: str, window: str, limit: int = 90) -> list[dict[str, Any]]:
    cursor = (
        get_db()
        .feature_series.find({"merchant_id": merchant_id, "name": name, "window": window})
        .sort("bucket", 1)
        .limit(limit)
    )
    return [
        {"bucket": row["bucket"], "value": row.get("value")}
        async for row in cursor
    ]
