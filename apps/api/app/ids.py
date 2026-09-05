from __future__ import annotations

import secrets
import time
import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def new_trace_id() -> str:
    return f"trace_{uuid.uuid4().hex}"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def millis() -> int:
    return int(time.time() * 1000)
