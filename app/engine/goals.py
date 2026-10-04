"""Goal trajectory engine.

A goal is "on track" when the projected value at its target date, from the
amount saved today plus the monthly contribution grown at the user's assumed
return, reaches the target. All projections are scenarios based on the user's
own inputs, not forecasts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .formatting import inr, rround
from .models import Goal, WithdrawalRequest

MAX_EXTENSION_MONTHS = 360


def months_between(start: date, end: date) -> int:
    m = (end.year - start.year) * 12 + (end.month - start.month)
    return max(m, 0)


def monthly_rate(annual_pct: float) -> float:
    return (1 + annual_pct / 100) ** (1 / 12) - 1


def project(saved: float, monthly: float, annual_pct: float, months: int) -> float:
    r = monthly_rate(annual_pct)
    if months <= 0:
        return saved
    if r == 0:
        return saved + monthly * months
    g = (1 + r) ** months
    return saved * g + monthly * (g - 1) / r


def annuity_factor(annual_pct: float, months: int) -> float:
    r = monthly_rate(annual_pct)
    if months <= 0:
        return 0.0
    if r == 0:
        return float(months)
    return ((1 + r) ** months - 1) / r


def goal_reduction(goal: Goal, amount: int, reason: Optional[str], invested_total: int) -> int:
    """How much of the goal's saved corpus a withdrawal draws down.

    If the withdrawal reason matches the goal's category, the withdrawal comes
    out of that goal's corpus first. Otherwise every goal is reduced in
    proportion to the share of the invested portfolio being withdrawn.
    """
    if amount <= 0 or goal.saved_amount <= 0:
        return 0
    if reason and reason == goal.category:
        return min(amount, goal.saved_amount)
    if invested_total <= 0:
        return 0
    share = min(amount / invested_total, 1.0)
    return min(rround(goal.saved_amount * share), goal.saved_amount)


@dataclass
class GoalImpact:
    goal: Goal
    months_left: int
    reduction: int
    saved_before: int
    saved_after: int
    projected_before: int
    projected_after: int
    on_track_before: bool
    on_track_after: bool
    affected: bool  # withdrawal reduces this goal's corpus
    triggered: bool  # materiality trigger 2: ends below required trajectory
    gap_after: int  # target minus projected after (0 if still on track)
    extra_monthly_needed: Optional[int]
    extension_months: Optional[int]
    explain: list

    @property
    def status_before(self) -> str:
        return "On track" if self.on_track_before else "Below current trajectory"

    @property
    def status_after(self) -> str:
        if not self.affected:
            return self.status_before
        return "On track" if self.on_track_after else "Below current trajectory"


def evaluate_goal(goal: Goal, amount: int, reason: Optional[str], invested_total: int, today: date) -> GoalImpact:
    n = months_between(today, goal.target_date)
    red = goal_reduction(goal, amount, reason, invested_total)
    before = rround(project(goal.saved_amount, goal.monthly_contribution, goal.expected_return_pct, n))
    after_saved = goal.saved_amount - red
    after = rround(project(after_saved, goal.monthly_contribution, goal.expected_return_pct, n))
    on_before = before >= goal.target_amount
    on_after = after >= goal.target_amount
    affected = red > 0
    triggered = affected and not on_after
    gap = max(goal.target_amount - after, 0)

    extra = None
    ext = None
    if gap > 0:
        f = annuity_factor(goal.expected_return_pct, n)
        if f > 0:
            extra = int(math.ceil(gap / f / 100.0) * 100)  # rounded up to nearest Rs 100
        for m in range(n + 1, n + MAX_EXTENSION_MONTHS + 1):
            if project(after_saved, goal.monthly_contribution, goal.expected_return_pct, m) >= goal.target_amount:
                ext = m - n
                break

    explain = [
        f"Target: {inr(goal.target_amount)} by {goal.target_date.strftime('%b %Y')} ({n} months away)",
        f"Saved towards this goal today: {inr(goal.saved_amount)}; monthly contribution {inr(goal.monthly_contribution)}; assumed return {goal.expected_return_pct:g}% a year (your input)",
        f"Projected at target date before withdrawal: {inr(before)}",
    ]
    if affected:
        rule = (
            "the reason matches this goal, so the withdrawal comes out of its corpus"
            if reason == goal.category
            else "reduced in proportion to the share of the portfolio withdrawn"
        )
        explain += [
            f"Withdrawal draws {inr(red)} from this goal ({rule})",
            f"Projected at target date after withdrawal: {inr(after)}",
        ]
    return GoalImpact(goal, n, red, goal.saved_amount, after_saved, before, after, on_before, on_after,
                      affected, triggered, gap, extra, ext, explain)
