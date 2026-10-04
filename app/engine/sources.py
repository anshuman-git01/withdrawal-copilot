"""Cross-asset source comparison and funding plans.

Costs come only from the Assumptions table (illustrative mock estimates).
Nothing here selects a source for the user: quotes are computed for every
source, and a plan only exists once the user builds one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .formatting import inr, num, pct, rround
from .models import ASSET_KEYS, ASSET_LABELS, SOURCE_KEYS, Profile

SETTLEMENT = {
    "mf": "Typically 1–3 business days",
    "stocks": "Market-dependent",
    "etfs": "Market-dependent",
    "fd": "Depends on bank terms",
    "cash": "Immediate / accessible cash",
}
MARKET_DISCLAIMER = "Actual taxes and charges depend on security, holding period, and transaction details."


def available(profile: Profile, key: str) -> int:
    return profile.cash if key == "cash" else profile.holdings.get(key)


def costs_for(profile: Profile, key: str, draw: int) -> list:
    """Return [(label, amount)] of illustrative deductions for drawing `draw` from `key`."""
    a = profile.assumptions
    if draw <= 0:
        return []
    if key == "mf":
        return [
            ("Mock estimated tax", rround(draw * a.mf_tax_rate_pct / 100)),
            (f"Mock exit load ({num(a.mf_exit_load_pct)}%)", rround(draw * a.mf_exit_load_pct / 100)),
        ]
    if key == "fd":
        return [(f"Illustrative premature-withdrawal impact ({num(a.fd_premature_pct)}%)",
                 rround(draw * a.fd_premature_pct / 100))]
    if key == "stocks":
        return [("Demo transaction/tax friction", rround(draw * a.stocks_friction_pct / 100))]
    if key == "etfs":
        return [("Demo transaction/tax friction", rround(draw * a.etfs_friction_pct / 100))]
    return []  # cash: not an investment liquidation


def allocation_after(profile: Profile, draws: dict) -> dict:
    """Invested allocation (percent) after removing `draws` (asset key -> rupees)."""
    h = profile.holdings
    remaining = {k: max(h.get(k) - draws.get(k, 0), 0) for k in ASSET_KEYS}
    total = sum(remaining.values())
    if total <= 0:
        return {k: 0.0 for k in ASSET_KEYS}
    return {k: remaining[k] / total * 100 for k in ASSET_KEYS}


def allocation_shift(profile: Profile, draws: dict) -> tuple:
    """Largest movement (percentage points) from target allocation, and which asset."""
    after = allocation_after(profile, draws)
    worst_key, worst = None, 0.0
    for k in ASSET_KEYS:
        d = abs(after[k] - profile.target_allocation.get(k, 0.0))
        if d > worst:
            worst_key, worst = k, d
    return worst, worst_key, after


@dataclass
class SourceQuote:
    key: str
    label: str
    available: int
    draw: int
    can_fully_cover: bool
    costs: list
    total_cost: int
    received: int
    settlement: str
    portfolio_pct: Optional[float]  # None for cash (not an investment liquidation)
    allocation_pp: float
    allocation_asset: Optional[str]
    allocation_triggered: bool
    cash_after: int
    liquidity_triggered: bool
    disclaimer: Optional[str]
    explain: list = field(default_factory=list)

    @property
    def status(self) -> str:
        return "Can cover the full amount" if self.can_fully_cover else "Partial source only"


def quote(profile: Profile, key: str, amount: int) -> SourceQuote:
    avail = available(profile, key)
    draw = min(amount, avail)
    costs = costs_for(profile, key, draw)
    total_cost = sum(c for _, c in costs)
    received = draw - total_cost
    invested = profile.holdings.total
    is_cash = key == "cash"

    draws = {} if is_cash else {key: draw}
    pp, pp_key, _ = allocation_shift(profile, draws)
    alloc_trig = pp > profile.thresholds.allocation_pp

    cash_after = profile.cash - (draw if is_cash else 0)
    liq_trig = is_cash and draw > 0 and cash_after < profile.liquidity_buffer

    explain = [f"Available in {ASSET_LABELS[key]}: {inr(avail)}", f"Drawn: {inr(draw)}"]
    for label, c in costs:
        explain.append(f"− {label}: {inr(c)}")
    explain.append(f"= Estimated amount received: {inr(received)}")
    if not is_cash:
        explain.append(f"Largest allocation move from your target: {num(pp, 1)} percentage points"
                       + (f" ({ASSET_LABELS[pp_key]})" if pp_key else ""))
    else:
        explain.append(f"Accessible cash after: {inr(cash_after)} vs your buffer of {inr(profile.liquidity_buffer)}")

    return SourceQuote(
        key=key,
        label=ASSET_LABELS[key],
        available=avail,
        draw=draw,
        can_fully_cover=avail >= amount,
        costs=costs,
        total_cost=total_cost,
        received=received,
        settlement=SETTLEMENT[key],
        portfolio_pct=None if is_cash or invested <= 0 else draw / invested * 100,
        allocation_pp=pp,
        allocation_asset=pp_key,
        allocation_triggered=alloc_trig,
        cash_after=cash_after,
        liquidity_triggered=liq_trig,
        disclaimer=MARKET_DISCLAIMER if key in ("stocks", "etfs") else None,
        explain=explain,
    )


def compare(profile: Profile, amount: int) -> list:
    return [quote(profile, k, amount) for k in SOURCE_KEYS]


@dataclass
class FundingPlan:
    """A user-built mix of sources. Never generated automatically."""

    allocations: dict  # source key -> rupees, user-entered
    lines: list
    gross: int
    total_cost: int
    received: int
    need: int
    gap: int  # need - gross (positive = still short)
    over: int  # gross - need (positive = more than needed)
    errors: list
    allocation_pp: float
    allocation_asset: Optional[str]
    allocation_triggered: bool
    cash_after: int
    liquidity_triggered: bool

    @property
    def is_complete(self) -> bool:
        return not self.errors and self.gap == 0 and self.over == 0 and self.gross > 0


def build_plan(profile: Profile, allocations: dict, need: int) -> FundingPlan:
    errors, lines = [], []
    clean = {}
    for k in SOURCE_KEYS:
        v = int(allocations.get(k, 0) or 0)
        if v < 0:
            errors.append(f"{ASSET_LABELS[k]}: enter an amount of ₹0 or more.")
            v = 0
        avail = available(profile, k)
        if v > avail:
            errors.append(f"{ASSET_LABELS[k]}: only {inr(avail)} is available.")
            v = avail
        if v:
            clean[k] = v
            costs = costs_for(profile, k, v)
            c = sum(x for _, x in costs)
            lines.append({"key": k, "label": ASSET_LABELS[k], "draw": v, "costs": costs, "cost": c, "received": v - c})
    gross = sum(clean.values())
    total_cost = sum(l["cost"] for l in lines)
    draws = {k: v for k, v in clean.items() if k != "cash"}
    pp, pp_key, _ = allocation_shift(profile, draws)
    cash_after = profile.cash - clean.get("cash", 0)
    return FundingPlan(
        allocations=clean,
        lines=lines,
        gross=gross,
        total_cost=total_cost,
        received=gross - total_cost,
        need=need,
        gap=max(need - gross, 0),
        over=max(gross - need, 0),
        errors=errors,
        allocation_pp=pp,
        allocation_asset=pp_key,
        allocation_triggered=pp > profile.thresholds.allocation_pp,
        cash_after=cash_after,
        liquidity_triggered=clean.get("cash", 0) > 0 and cash_after < profile.liquidity_buffer,
    )


def describe_plan(plan: FundingPlan) -> str:
    return " + ".join(f"{l['label']} {inr(l['draw'])}" for l in plan.lines) or "No sources chosen"


__all__ = ["compare", "quote", "build_plan", "describe_plan", "FundingPlan", "SourceQuote", "pct"]
