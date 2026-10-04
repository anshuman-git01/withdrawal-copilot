"""Number formatting. One source for every displayed figure."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def rround(x: float) -> int:
    """Round half up to whole rupees (avoids banker's rounding surprises)."""
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _group_indian(n: int) -> str:
    s = str(abs(n))
    if len(s) <= 3:
        out = s
    else:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        out = ",".join(parts) + "," + tail
    return ("-" if n < 0 else "") + out


def inr(n: float) -> str:
    """Full Indian format: 170000 -> ₹1,70,000"""
    n = rround(n)
    return ("-₹" if n < 0 else "₹") + _group_indian(abs(n))


def _trim(value: float, unit: str, two_dp: bool) -> str:
    # Lakh/crore: 2 decimals when exact (1.70L), 3 when that is exact (1.638L),
    # otherwise 2 decimals rounded (1.64L).
    if two_dp:
        for dp in (2, 3):
            q = Decimal(str(value)).quantize(Decimal(10) ** -dp, rounding=ROUND_HALF_UP)
            if q == Decimal(str(value)):
                return f"{q}{unit}"
        return f"{Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}{unit}"
    # Thousands: integer when exact (80K), else one decimal (6.2K).
    q0 = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if q0 == Decimal(str(value)):
        return f"{q0}{unit}"
    return f"{Decimal(str(value)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}{unit}"


def inr_short(n: float) -> str:
    """Compact format: ₹1.70L, ₹1.638L, ₹80K, ₹6.2K, ₹2.50L, ₹1.2Cr"""
    n = rround(n)
    sign = "-" if n < 0 else ""
    a = abs(n)
    if a >= 10_000_000:
        body = _trim(a / 10_000_000, "Cr", True)
    elif a >= 100_000:
        body = _trim(a / 100_000, "L", True)
    elif a >= 1_000:
        body = _trim(a / 1_000, "K", False)
    else:
        body = str(a)
    return f"{sign}₹{body}"


def pct(x: float, dp: int = 0) -> str:
    q = Decimal(str(x)).quantize(Decimal(10) ** -dp if dp else Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{q}%"


def num(x: float, dp: int = 2) -> str:
    q = Decimal(str(x)).quantize(Decimal(10) ** -dp, rounding=ROUND_HALF_UP)
    s = f"{q}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def nice_date(d) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"
