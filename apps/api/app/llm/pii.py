from __future__ import annotations

import re
from typing import Any

CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"\b(?:\+91[\s-]?)?[6-9]\d{9}\b")
CVV = re.compile(r"\b\d{3,4}\b")


UNTRUSTED_KEYS = {"name", "email", "phone", "address", "card", "pan", "vpa", "account_number"}


def mask_text(text: str) -> str:
    text = CARD.sub("[CARD]", text)
    text = EMAIL.sub("[EMAIL]", text)
    text = PHONE.sub("[PHONE]", text)
    return text


def sanitize_untrusted(text: str) -> str:
    cleaned = mask_text(text or "")
    return f"<UNTRUSTED_MERCHANT_OR_CUSTOMER_TEXT>{cleaned}</UNTRUSTED_MERCHANT_OR_CUSTOMER_TEXT>"


def strip_pii(payload: Any) -> Any:
    if isinstance(payload, dict):
        out = {}
        for key, value in payload.items():
            if key.lower() in UNTRUSTED_KEYS:
                continue
            if key.lower() in {"cvv", "card_number", "password", "secret", "ifsc"}:
                continue
            out[key] = strip_pii(value)
        return out
    if isinstance(payload, list):
        return [strip_pii(v) for v in payload]
    if isinstance(payload, str):
        return mask_text(payload)
    return payload
