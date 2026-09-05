from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.db import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(subject: dict[str, Any]) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {**subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


async def current_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    db = get_db()
    if x_api_key:
        key = await db.api_keys.find_one({"key": x_api_key, "active": True})
        if not key:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {
            "type": "api_key",
            "merchant_id": key["merchant_id"],
            "tenant_id": key["tenant_id"],
            "roles": key.get("roles", ["merchant_admin"]),
            "user_id": key.get("created_by"),
        }
    if authorization and authorization.lower().startswith("bearer "):
        payload = decode_token(authorization.split(" ", 1)[1])
        user = await db.users.find_one({"user_id": payload.get("sub")})
        if not user or not user.get("active", True):
            raise HTTPException(status_code=401, detail="Unknown user")
        return {
            "type": "user",
            "merchant_id": user["merchant_id"],
            "tenant_id": user["tenant_id"],
            "roles": user.get("roles", ["operator"]),
            "user_id": user["user_id"],
            "email": user["email"],
        }
    raise HTTPException(status_code=401, detail="Authentication required")


async def authorized_merchant(
    principal: Annotated[dict[str, Any], Depends(current_principal)],
    x_merchant_id: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    merchant_id = principal["merchant_id"]
    if x_merchant_id and x_merchant_id != merchant_id and "platform_admin" not in principal.get("roles", []):
        raise HTTPException(status_code=403, detail="Caller is not authorized for this merchant")
    return principal


def require_roles(*roles: str):
    async def checker(principal: Annotated[dict[str, Any], Depends(authorized_merchant)]) -> dict[str, Any]:
        if "platform_admin" in principal.get("roles", []):
            return principal
        if not set(roles) & set(principal.get("roles", [])):
            raise HTTPException(status_code=403, detail="Insufficient role")
        return principal

    return checker
