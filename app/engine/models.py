"""Data models for the Withdrawal Copilot engine.

Pure standard library (dataclasses) so the engine can be tested and reused
without any web framework. Every rupee value is an integer number of rupees.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

ASSET_KEYS = ["stocks", "etfs", "mf", "fd"]
ASSET_LABELS = {
    "stocks": "Stocks",
    "etfs": "ETFs",
    "mf": "Mutual Funds",
    "fd": "Fixed Deposits",
    "cash": "Accessible cash",
}
SOURCE_KEYS = ["mf", "stocks", "etfs", "fd", "cash"]

REASONS = [
    "Emergency",
    "Medical",
    "House / Property",
    "Education",
    "Wedding",
    "Debt repayment",
    "Family need",
    "Other",
]
# Reasons that describe a specific financial need. The behaviour check never
# fires for these.
SPECIFIC_REASONS = [r for r in REASONS if r != "Other"]


@dataclass
class Holdings:
    stocks: int = 0
    etfs: int = 0
    mf: int = 0
    fd: int = 0

    @property
    def total(self) -> int:
        return self.stocks + self.etfs + self.mf + self.fd

    def get(self, key: str) -> int:
        return int(getattr(self, key))

    def as_dict(self) -> dict:
        return {k: self.get(k) for k in ASSET_KEYS}


@dataclass
class Goal:
    id: str
    name: str
    category: str  # matches a withdrawal reason, e.g. "House / Property"
    target_amount: int
    target_date: date
    saved_amount: int  # part of the invested portfolio earmarked for this goal
    monthly_contribution: int
    expected_return_pct: float  # user assumption, annual


@dataclass
class Assumptions:
    """Illustrative mock cost assumptions. Editable on the Assumptions page."""

    # Mock MF tax expressed as a share of the amount withdrawn. The demo value
    # reproduces exactly Rs 4,500 on Rs 1,70,000 (4,500 / 1,70,000).
    mf_tax_rate_pct: float = 4500 / 170000 * 100
    mf_exit_load_pct: float = 1.0
    fd_premature_pct: float = 1.0
    stocks_friction_pct: float = 0.0
    etfs_friction_pct: float = 0.0
    borrow_limit: int = 250000
    borrow_rate_low_pct: float = 9.0
    borrow_rate_high_pct: float = 11.0
    borrow_collateral: str = "Eligible Stocks, ETFs and eligible Mutual Funds"


@dataclass
class Thresholds:
    portfolio_pct: float = 10.0  # Trigger 1: withdrawal >= this % of invested portfolio
    allocation_pp: float = 5.0  # Trigger 4: allocation moves by more than this many points
    market_move_pct: float = 6.0  # Behaviour check market threshold


@dataclass
class Profile:
    holdings: Holdings
    cash: int
    liquidity_buffer: int
    target_allocation: dict  # asset key -> percent of invested portfolio
    goals: list
    assumptions: Assumptions = field(default_factory=Assumptions)
    thresholds: Thresholds = field(default_factory=Thresholds)
    # Observed market movement for the relevant period (percent, negative = fall).
    market_move_pct: float = 0.0


@dataclass
class WithdrawalRequest:
    amount: int
    needed_by: date
    reason: Optional[str]  # None or "" means no reason selected


def current_allocation(holdings: Holdings) -> dict:
    total = holdings.total
    if total <= 0:
        return {k: 0.0 for k in ASSET_KEYS}
    return {k: holdings.get(k) / total * 100 for k in ASSET_KEYS}


def demo_profile() -> Profile:
    """The canonical case-competition demo state. Do not change these values."""
    holdings = Holdings(stocks=80000, etfs=60000, mf=530000, fd=100000)
    return Profile(
        holdings=holdings,
        cash=40000,
        # User-configurable settings. The spec does not fix these, so they are
        # seeded as editable inputs, chosen so the demo matches the spec's
        # trigger state (liquidity and allocation not triggered).
        liquidity_buffer=25000,
        target_allocation={k: round(v, 1) for k, v in current_allocation(holdings).items()},
        goals=[
            Goal(
                id="house",
                name="House",
                category="House / Property",
                target_amount=2400000,
                target_date=date(2030, 12, 31),
                saved_amount=600000,
                monthly_contribution=25000,
                expected_return_pct=10.0,
            )
        ],
        assumptions=Assumptions(),
        thresholds=Thresholds(),
        market_move_pct=0.0,
    )


def demo_request() -> WithdrawalRequest:
    return WithdrawalRequest(amount=170000, needed_by=date(2026, 11, 30), reason="House / Property")


# ---------------------------------------------------------------- serialization

def _date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(v)


def profile_to_dict(p: Profile) -> dict:
    d = asdict(p)
    for g in d["goals"]:
        g["target_date"] = g["target_date"].isoformat()
    return d


def profile_from_dict(d: dict) -> Profile:
    return Profile(
        holdings=Holdings(**d["holdings"]),
        cash=int(d["cash"]),
        liquidity_buffer=int(d["liquidity_buffer"]),
        target_allocation={k: float(v) for k, v in d["target_allocation"].items()},
        goals=[Goal(**{**g, "target_date": _date(g["target_date"])}) for g in d["goals"]],
        assumptions=Assumptions(**d.get("assumptions", {})),
        thresholds=Thresholds(**d.get("thresholds", {})),
        market_move_pct=float(d.get("market_move_pct", 0.0)),
    )


def request_to_dict(r: WithdrawalRequest) -> dict:
    return {"amount": r.amount, "needed_by": r.needed_by.isoformat(), "reason": r.reason}


def request_from_dict(d: dict) -> WithdrawalRequest:
    return WithdrawalRequest(amount=int(d["amount"]), needed_by=_date(d["needed_by"]), reason=d.get("reason") or None)
