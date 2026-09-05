from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.db import find_one, get_db, insert_one
from app.ids import new_id
from app.security import authorized_merchant, create_access_token, hash_password, verify_password
from app.timeutil import utcnow

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    merchant_name: str
    cash_reserve_minimum_paise: int = 2_000_000_00

    @field_validator("email")
    @classmethod
    def email_present(cls, value: str) -> str:
        if "@" not in value or "." not in value.split("@")[-1]:
            raise ValueError("email must look like an address")
        return value.lower()


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def email_present(cls, value: str) -> str:
        if "@" not in value:
            raise ValueError("email required")
        return value.lower()


@router.post("/register")
async def register(body: RegisterRequest) -> dict[str, Any]:
    db = get_db()
    if await db.users.find_one({"email": body.email.lower()}):
        raise HTTPException(status_code=409, detail="Email already registered")
    tenant_id = new_id("ten")
    merchant_id = new_id("merch")
    user_id = new_id("user")
    now = utcnow()
    await insert_one(
        "tenants",
        {"tenant_id": tenant_id, "name": body.merchant_name, "created_at": now},
    )
    await insert_one(
        "merchants",
        {
            "merchant_id": merchant_id,
            "tenant_id": tenant_id,
            "name": body.merchant_name,
            "active": True,
            "created_at": now,
        },
    )
    await insert_one(
        "users",
        {
            "user_id": user_id,
            "email": body.email.lower(),
            "password_hash": hash_password(body.password),
            "merchant_id": merchant_id,
            "tenant_id": tenant_id,
            "roles": ["merchant_admin"],
            "active": True,
            "created_at": now,
        },
    )
    await insert_one(
        "policies",
        {
            "merchant_id": merchant_id,
            "cash_reserve_minimum_paise": body.cash_reserve_minimum_paise,
            "automatic_refund_maximum_paise": 5000_00,
            "payout_automatic_limit_paise": 5_00_000_00,
            "autonomy_level": "recommend",
            "weights": {"growth": 0.3, "cash": 0.5, "risk": 0.2},
            "created_at": now,
        },
    )
    token = create_access_token({"sub": user_id, "merchant_id": merchant_id})
    return {"access_token": token, "merchant_id": merchant_id, "tenant_id": tenant_id, "user_id": user_id}


@router.post("/login")
async def login(body: LoginRequest) -> dict[str, Any]:
    user = await find_one("users", {"email": body.email.lower()})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user["user_id"], "merchant_id": user["merchant_id"]})
    merchant = await find_one("merchants", {"merchant_id": user["merchant_id"]})
    return {
        "access_token": token,
        "merchant_id": user["merchant_id"],
        "tenant_id": user["tenant_id"],
        "user_id": user["user_id"],
        "merchant_name": (merchant or {}).get("name"),
    }


@router.get("/me")
async def me(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
    merchant = await find_one("merchants", {"merchant_id": principal["merchant_id"]})
    return {**principal, "merchant_name": (merchant or {}).get("name")}
