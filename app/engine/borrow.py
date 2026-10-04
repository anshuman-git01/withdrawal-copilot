"""Sell-vs-borrow: illustrative borrowing figures only.

No EMI, no foreclosure charge, nothing above the eligible limit, and no
recommendation either way.
"""
from __future__ import annotations

from dataclasses import dataclass

from .formatting import inr, num, rround
from .models import Profile

BORROW_DISCLAIMERS = [
    "Illustrative comparison — not financial advice or a lender quote.",
    "Actual rate, LTV, collateral eligibility and terms depend on the lender and asset.",
]


@dataclass
class BorrowQuote:
    limit: int
    need: int
    within_limit: bool
    borrowable: int  # never above the limit
    remaining_room: int
    rate_low: float
    rate_high: float
    rate_mid: float
    interest_1y: int
    collateral: str
    explain: list

    @property
    def rate_band(self) -> str:
        return f"{num(self.rate_low)}–{num(self.rate_high)}% p.a."


def borrow_quote(profile: Profile, need: int) -> BorrowQuote:
    a = profile.assumptions
    mid = (a.borrow_rate_low_pct + a.borrow_rate_high_pct) / 2
    within = need <= a.borrow_limit
    borrowable = min(need, a.borrow_limit)
    interest = rround(borrowable * mid / 100)
    explain = [
        f"Eligible borrowing limit (illustrative): {inr(a.borrow_limit)}",
        f"Amount considered: {inr(borrowable)}" + ("" if within else f" (your need of {inr(need)} is above the limit)"),
        f"{inr(borrowable)} × {num(mid)}% = {inr(interest)} illustrative interest for one year",
    ]
    return BorrowQuote(a.borrow_limit, need, within, borrowable, max(a.borrow_limit - borrowable, 0),
                       a.borrow_rate_low_pct, a.borrow_rate_high_pct, mid, interest, a.borrow_collateral, explain)


@dataclass
class BehaviourCheck:
    triggered: bool
    simulated: bool
    market_move_pct: float
    reason: str
    message: str
    status_copy: str


def behaviour_check(profile: Profile, reason, simulate: bool = False) -> BehaviourCheck:
    """Fires only when market movement >= threshold AND reason is Other or blank.

    `simulate` is the prototype-only demo toggle. It changes what this check
    sees (6% fall, unclear reason) and nothing else in the engine.
    """
    threshold = profile.thresholds.market_move_pct
    move = -threshold if simulate else profile.market_move_pct
    eff_reason = "Other" if simulate else (reason or "")
    unclear = eff_reason in ("", "Other")
    triggered = abs(move) >= threshold and unclear
    direction = "fell" if move < 0 else "rose"
    message = f"Markets {direction} {num(abs(move))}% this week. Is this withdrawal related?"
    if triggered:
        status = message
    elif not unclear:
        status = "Your stated need is specific, so no market-behaviour prompt is shown."
    else:
        status = f"Market movement is below the {num(threshold)}% threshold, so no prompt is shown."
    return BehaviourCheck(triggered, simulate, move, reason or "Not selected", message, status)
