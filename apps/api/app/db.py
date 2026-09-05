from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.config import get_settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


COLLECTIONS = [
    "tenants",
    "merchants",
    "users",
    "api_keys",
    "customers",
    "products",
    "orders",
    "payments",
    "refunds",
    "subscriptions",
    "invoices",
    "settlements",
    "payouts",
    "disputes",
    "cash_accounts",
    "employees",
    "vendors",
    "events",
    "processed_events",
    "merchant_states",
    "features",
    "feature_series",
    "causal_edges",
    "predictions",
    "recommendations",
    "actions",
    "approvals",
    "policies",
    "agent_registry",
    "agent_runs",
    "agent_trust",
    "outcomes",
    "memories",
    "alerts",
    "simulations",
    "circuit_breakers",
    "audit_logs",
    "relationships",
]


async def connect() -> AsyncIOMotorDatabase:
    global _client, _db
    settings = get_settings()
    _client = AsyncIOMotorClient(settings.mongo_uri)
    _db = _client[settings.mongo_db]
    await ensure_indexes(_db)
    return _db


async def disconnect() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database is not connected")
    return _db


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    await db.events.create_indexes(
        [
            IndexModel([("event_id", ASCENDING)], unique=True),
            IndexModel([("merchant_id", ASCENDING), ("timestamp", DESCENDING)]),
            IndexModel([("merchant_id", ASCENDING), ("event_type", ASCENDING), ("timestamp", DESCENDING)]),
            IndexModel([("trace_id", ASCENDING)]),
        ]
    )
    await db.processed_events.create_indexes(
        [IndexModel([("event_id", ASCENDING)], unique=True)]
    )
    await db.merchants.create_indexes([IndexModel([("merchant_id", ASCENDING)], unique=True)])
    await db.users.create_indexes(
        [
            IndexModel([("email", ASCENDING)], unique=True),
            IndexModel([("merchant_id", ASCENDING)]),
        ]
    )
    await db.customers.create_indexes(
        [
            IndexModel([("merchant_id", ASCENDING), ("customer_id", ASCENDING)], unique=True),
            IndexModel([("merchant_id", ASCENDING), ("segment", ASCENDING)]),
        ]
    )
    await db.orders.create_indexes(
        [IndexModel([("merchant_id", ASCENDING), ("order_id", ASCENDING)], unique=True)]
    )
    await db.payments.create_indexes(
        [
            IndexModel([("merchant_id", ASCENDING), ("payment_id", ASCENDING)], unique=True),
            IndexModel([("merchant_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("merchant_id", ASCENDING), ("status", ASCENDING)]),
        ]
    )
    await db.invoices.create_indexes(
        [IndexModel([("merchant_id", ASCENDING), ("invoice_id", ASCENDING)], unique=True)]
    )
    await db.settlements.create_indexes(
        [IndexModel([("merchant_id", ASCENDING), ("settlement_id", ASCENDING)], unique=True)]
    )
    await db.payouts.create_indexes(
        [IndexModel([("merchant_id", ASCENDING), ("payout_id", ASCENDING)], unique=True)]
    )
    await db.disputes.create_indexes(
        [IndexModel([("merchant_id", ASCENDING), ("dispute_id", ASCENDING)], unique=True)]
    )
    await db.refunds.create_indexes(
        [IndexModel([("merchant_id", ASCENDING), ("refund_id", ASCENDING)], unique=True)]
    )
    await db.merchant_states.create_indexes(
        [
            IndexModel([("merchant_id", ASCENDING), ("computed_at", DESCENDING)]),
            IndexModel([("merchant_id", ASCENDING), ("is_current", ASCENDING)]),
        ]
    )
    await db.features.create_indexes(
        [IndexModel([("merchant_id", ASCENDING), ("name", ASCENDING), ("window", ASCENDING)], unique=True)]
    )
    await db.feature_series.create_indexes(
        [
            IndexModel(
                [("merchant_id", ASCENDING), ("name", ASCENDING), ("window", ASCENDING), ("bucket", ASCENDING)],
                unique=True,
            )
        ]
    )
    await db.recommendations.create_indexes(
        [IndexModel([("merchant_id", ASCENDING), ("created_at", DESCENDING)])]
    )
    await db.actions.create_indexes(
        [
            IndexModel([("action_id", ASCENDING)], unique=True),
            IndexModel([("merchant_id", ASCENDING), ("created_at", DESCENDING)]),
        ]
    )
    await db.approvals.create_indexes([IndexModel([("token", ASCENDING)], unique=True)])
    await db.policies.create_indexes([IndexModel([("merchant_id", ASCENDING)], unique=True)])
    await db.agent_trust.create_indexes(
        [IndexModel([("merchant_id", ASCENDING), ("agent_id", ASCENDING)], unique=True)]
    )
    await db.memories.create_indexes(
        [IndexModel([("merchant_id", ASCENDING), ("kind", ASCENDING), ("created_at", DESCENDING)])]
    )
    await db.alerts.create_indexes(
        [IndexModel([("merchant_id", ASCENDING), ("created_at", DESCENDING)])]
    )
    await db.audit_logs.create_indexes(
        [IndexModel([("merchant_id", ASCENDING), ("created_at", DESCENDING)])]
    )
    await db.relationships.create_indexes(
        [
            IndexModel(
                [
                    ("merchant_id", ASCENDING),
                    ("from_type", ASCENDING),
                    ("from_id", ASCENDING),
                    ("to_type", ASCENDING),
                    ("to_id", ASCENDING),
                    ("rel", ASCENDING),
                ],
                unique=True,
            )
        ]
    )


def jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if k != "_id"}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, datetime):
        # Mongo hands back naive datetimes even though everything is written in
        # UTC. Serialising them without an offset makes clients read them as
        # local time, so stamp UTC back on before they leave the process.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    name = type(value).__name__
    if name == "ObjectId":
        return str(value)
    return value


def strip_id(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    return jsonable(doc)


async def find_one(collection: str, query: dict[str, Any]) -> dict[str, Any] | None:
    return strip_id(await get_db()[collection].find_one(query))


async def find_many(
    collection: str,
    query: dict[str, Any],
    sort: list[tuple[str, int]] | None = None,
    limit: int = 200,
    skip: int = 0,
) -> list[dict[str, Any]]:
    cursor = get_db()[collection].find(query)
    if sort:
        cursor = cursor.sort(sort)
    if skip:
        cursor = cursor.skip(skip)
    if limit:
        cursor = cursor.limit(limit)
    return [strip_id(d) or {} async for d in cursor]


async def insert_one(collection: str, doc: dict[str, Any]) -> str:
    result = await get_db()[collection].insert_one(doc)
    doc.pop("_id", None)
    return str(result.inserted_id)


async def update_one(collection: str, query: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> None:
    await get_db()[collection].update_one(query, update, upsert=upsert)


async def replace_one(collection: str, query: dict[str, Any], doc: dict[str, Any], upsert: bool = False) -> None:
    await get_db()[collection].replace_one(query, doc, upsert=upsert)


async def count(collection: str, query: dict[str, Any]) -> int:
    return await get_db()[collection].count_documents(query)


async def aggregate(collection: str, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [strip_id(d) or d async for d in get_db()[collection].aggregate(pipeline)]


async def aggregate_grouped(collection: str, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregation that keeps `_id`.

    In a `$group` stage `_id` is the group key, not a Mongo document id, so the
    usual `strip_id` would throw the answer away.
    """
    rows: list[dict[str, Any]] = []
    async for doc in get_db()[collection].aggregate(pipeline):
        rows.append({key: jsonable(value) for key, value in doc.items()})
    return rows
