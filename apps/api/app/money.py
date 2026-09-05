"""Paise-first money. Razorpay stores INR amounts as integer paise."""

from __future__ import annotations


def paise(rupees: float | int) -> int:
    return int(round(float(rupees) * 100))


def rupees(amount_paise: int | float | None) -> float:
    if amount_paise is None:
        return 0.0
    return round(int(amount_paise) / 100.0, 2)


def format_inr(amount_paise: int | float | None) -> str:
    value = rupees(amount_paise)
    abs_value = abs(value)
    sign = "-" if value < 0 else ""
    if abs_value >= 10_00_000:
        return f"{sign}₹{abs_value / 10_00_000:.2f}L"
    if abs_value >= 1_000:
        return f"{sign}₹{abs_value / 1_000:.2f}K"
    return f"{sign}₹{abs_value:.2f}"
