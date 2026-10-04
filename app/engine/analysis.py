"""Materiality engine + orchestration.

Materiality is a transparent OR of four triggers. No weighted score exists.

Screen 3 evaluates it source-agnostically (no source chosen yet): the
withdrawal is assumed to come proportionally from investments, so accessible
cash and allocation are unchanged. Once the user builds a funding plan, the
same triggers are re-evaluated against that plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .borrow import BehaviourCheck, BorrowQuote, behaviour_check, borrow_quote
from .formatting import inr, inr_short, num, pct
from .goals import GoalImpact, evaluate_goal
from .models import ASSET_LABELS, Profile, WithdrawalRequest
from .sources import FundingPlan, SourceQuote, compare, quote


@dataclass
class Trigger:
    key: str
    name: str
    triggered: bool
    reason_copy: str
    detail: str


@dataclass
class Materiality:
    triggers: list
    significant: bool
    scope: str  # "before choosing a source" or "for your funding plan"

    @property
    def reasons(self) -> list:
        return [t for t in self.triggers if t.triggered]


@dataclass
class Validation:
    errors: dict = field(default_factory=dict)  # field -> message
    notices: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(profile: Profile, amount: Optional[int], needed_by: Optional[date], today: date) -> Validation:
    v = Validation()
    if amount is None or amount <= 0:
        v.errors["amount"] = "Enter an amount greater than ₹0."
    if needed_by is None:
        v.errors["date"] = "Choose the date you need the money by."
    elif needed_by < today:
        v.errors["date"] = "Choose a future date for this prototype."
    if amount and amount > 0:
        best_single = max([profile.holdings.get(k) for k in ("stocks", "etfs", "mf", "fd")] + [profile.cash])
        total = profile.holdings.total + profile.cash
        if amount > total:
            v.notices.append(
                f"{inr(amount)} is more than your invested portfolio and accessible cash combined ({inr(total)}). "
                "Borrowing can still be compared within its eligible limit.")
        elif amount > best_single:
            v.notices.append(f"{inr(amount)} cannot be fully funded from a single source in this demo.")
    return v


def portfolio_pct(profile: Profile, amount: int) -> float:
    total = profile.holdings.total
    return amount / total * 100 if total else 0.0


def materiality(profile: Profile, request: WithdrawalRequest, goals: list,
                plan: Optional[FundingPlan] = None) -> Materiality:
    t = profile.thresholds
    invested_amount = request.amount if plan is None else sum(
        v for k, v in plan.allocations.items() if k != "cash")
    p = portfolio_pct(profile, invested_amount)
    t1 = Trigger("portfolio", "Portfolio impact", p >= t.portfolio_pct,
                 f"{pct(p)} of your invested portfolio",
                 f"{inr(invested_amount)} ÷ {inr(profile.holdings.total)} = {num(p, 2)}% "
                 f"(threshold: {num(t.portfolio_pct)}% or more)")

    hit = [g for g in goals if g.triggered]
    t2 = Trigger("goal", "Goal impact", bool(hit),
                 (f"Your {hit[0].goal.name} goal is affected" if len(hit) == 1
                  else f"{len(hit)} goals are affected") if hit else "No tracked goal falls below its trajectory",
                 "A tracked goal ends below its required trajectory after this withdrawal" if hit
                 else "Every tracked goal stays on its required trajectory")

    if plan is None:
        t3_detail = (f"No accessible cash is used before you choose a source. {inr(profile.cash)} stays available "
                     f"(your buffer: {inr(profile.liquidity_buffer)}).")
        t3 = Trigger("liquidity", "Liquidity buffer", False,
                     "Accessible cash stays above your buffer", t3_detail)
        t4 = Trigger("allocation", "Allocation", False, "Allocation unchanged before choosing a source",
                     "Assessed per source on the comparison screen. A proportional withdrawal leaves your mix unchanged.")
        scope = "before choosing a source"
    else:
        t3 = Trigger("liquidity", "Liquidity buffer", plan.liquidity_triggered,
                     ("Accessible cash falls below your buffer" if plan.liquidity_triggered
                      else "Accessible cash stays above your buffer"),
                     f"Accessible cash after: {inr(plan.cash_after)} vs buffer {inr(profile.liquidity_buffer)}")
        asset = ASSET_LABELS.get(plan.allocation_asset or "", "")
        t4 = Trigger("allocation", "Allocation", plan.allocation_triggered,
                     (f"Allocation moves {num(plan.allocation_pp, 1)} points" if plan.allocation_triggered
                      else "Allocation stays within your target range"),
                     f"Largest move from target: {num(plan.allocation_pp, 1)} points"
                     + (f" ({asset})" if asset else "") + f" (threshold: more than {num(t.allocation_pp)} points)")
        scope = "for your funding plan"
    triggers = [t1, t2, t3, t4]
    return Materiality(triggers, any(x.triggered for x in triggers), scope)


@dataclass
class Analysis:
    profile: Profile
    request: WithdrawalRequest
    today: date
    invested: int
    cash: int
    pct: float
    goals: list
    materiality: Materiality
    plan_materiality: Optional[Materiality]
    sources: list
    mf: SourceQuote
    borrow: BorrowQuote
    behaviour: BehaviourCheck
    validation: Validation
    plan: Optional[FundingPlan]

    @property
    def primary_goal(self) -> Optional[GoalImpact]:
        for g in self.goals:
            if self.request.reason and g.goal.category == self.request.reason:
                return g
        affected = [g for g in self.goals if g.affected]
        return affected[0] if affected else (self.goals[0] if self.goals else None)

    @property
    def headline(self) -> str:
        parts = [f"This withdrawal is {pct(self.pct)} of your invested portfolio"]
        hit = [g for g in self.goals if g.triggered]
        if hit:
            parts.append(f"affects your {hit[0].goal.name} goal")
        return " and ".join(parts) + "."

    @property
    def full_cover_sources(self) -> list:
        return [s for s in self.sources if s.can_fully_cover]


def analyze(profile: Profile, request: WithdrawalRequest, today: date, simulate_behaviour: bool = False,
            plan: Optional[FundingPlan] = None) -> Analysis:
    goals = [evaluate_goal(g, request.amount, request.reason, profile.holdings.total, today) for g in profile.goals]
    mat = materiality(profile, request, goals)
    plan_mat = None
    if plan is not None and plan.gross > 0:
        invested_draw = sum(v for k, v in plan.allocations.items() if k != "cash")
        plan_goals = [evaluate_goal(g, invested_draw, request.reason, profile.holdings.total, today)
                      for g in profile.goals]
        plan_mat = materiality(profile, request, plan_goals, plan)
    return Analysis(
        profile=profile,
        request=request,
        today=today,
        invested=profile.holdings.total,
        cash=profile.cash,
        pct=portfolio_pct(profile, request.amount),
        goals=goals,
        materiality=mat,
        plan_materiality=plan_mat,
        sources=compare(profile, request.amount),
        mf=quote(profile, "mf", request.amount),
        borrow=borrow_quote(profile, request.amount),
        behaviour=behaviour_check(profile, request.reason, simulate_behaviour),
        validation=validate(profile, request.amount, request.needed_by, today),
        plan=plan,
    )


__all__ = ["analyze", "Analysis", "validate", "materiality", "inr_short"]
