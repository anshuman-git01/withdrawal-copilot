"""Section 39 checklist as automated tests, plus generalisation checks."""
from datetime import date

from app.engine import analyze, demo_profile, demo_request
from app.engine.analysis import validate
from app.engine.formatting import inr, inr_short, pct
from app.engine.models import WithdrawalRequest
from app.engine.sources import build_plan

TODAY = date(2026, 10, 4)


def demo(simulate=False, plan=None):
    return analyze(demo_profile(), demo_request(), TODAY, simulate, plan)


def test_portfolio_totals():
    a = demo()
    assert a.invested == 770000
    assert a.cash == 40000
    assert inr_short(a.invested) == "₹7.70L"
    assert inr_short(a.invested + a.cash) == "₹8.10L"
    h = a.profile.holdings
    assert (h.stocks, h.etfs, h.mf, h.fd) == (80000, 60000, 530000, 100000)


def test_withdrawal_percentage():
    a = demo()
    assert round(a.pct, 2) == 22.08
    assert pct(a.pct) == "22%"
    assert a.headline == "This withdrawal is 22% of your invested portfolio and affects your House goal."


def test_demo_trigger_state():
    m = demo().materiality
    state = {t.key: t.triggered for t in m.triggers}
    assert state == {"portfolio": True, "goal": True, "liquidity": False, "allocation": False}
    assert m.significant is True
    assert [t.reason_copy for t in m.reasons] == ["22% of your invested portfolio", "Your House goal is affected"]


def test_goal_trajectory():
    g = demo().primary_goal
    assert g.status_before == "On track"
    assert g.status_after == "Below current trajectory"
    assert g.affected and g.triggered


def test_mf_costs_exact():
    mf = demo().mf
    assert dict((k.split(" (")[0], v) for k, v in mf.costs) == {"Mock estimated tax": 4500, "Mock exit load": 1700}
    assert mf.total_cost == 6200
    assert mf.received == 163800
    assert inr_short(mf.received) == "₹1.638L"
    assert inr_short(mf.total_cost) == "₹6.2K"
    assert mf.can_fully_cover


def test_other_sources():
    s = {q.key: q for q in demo().sources}
    assert s["fd"].total_cost == 1000 and s["fd"].received == 99000 and not s["fd"].can_fully_cover
    assert s["stocks"].received == 80000 and s["stocks"].total_cost == 0 and s["stocks"].status == "Partial source only"
    assert s["etfs"].received == 60000 and s["etfs"].total_cost == 0
    assert s["cash"].received == 40000 and s["cash"].portfolio_pct is None
    assert [q.key for q in demo().full_cover_sources] == ["mf"]


def test_borrowing():
    b = demo().borrow
    assert b.limit == 250000 and b.need == 170000 and b.within_limit
    assert b.remaining_room == 80000
    assert b.rate_band == "9–11% p.a."
    assert b.rate_mid == 10
    assert b.interest_1y == 17000


def test_behaviour_check():
    a = demo()
    assert not a.behaviour.triggered
    assert a.behaviour.status_copy == "Your stated need is specific, so no market-behaviour prompt is shown."
    s = demo(simulate=True)
    assert s.behaviour.triggered
    assert s.behaviour.message == "Markets fell 6% this week. Is this withdrawal related?"
    # toggle must not alter any calculation
    assert (s.pct, s.mf.received, s.borrow.interest_1y) == (a.pct, a.mf.received, a.borrow.interest_1y)


def test_behaviour_rule_generalised():
    p = demo_profile()
    p.market_move_pct = -6.0
    for reason, expected in [("Other", True), (None, True), ("Medical", False), ("House / Property", False)]:
        r = WithdrawalRequest(170000, date(2026, 11, 30), reason)
        assert analyze(p, r, TODAY).behaviour.triggered is expected, reason
    p.market_move_pct = -5.9
    assert not analyze(p, WithdrawalRequest(170000, date(2026, 11, 30), "Other"), TODAY).behaviour.triggered


def test_mf_plan_reports_allocation_shift():
    plan = build_plan(demo_profile(), {"mf": 170000}, 170000)
    assert plan.is_complete
    assert round(plan.allocation_pp, 1) == 8.8
    a = demo(plan=plan)
    trig = {t.key: t.triggered for t in a.plan_materiality.triggers}
    assert trig["allocation"] is True
    # Screen 3 (source-agnostic) remains as specified
    assert {t.key: t.triggered for t in a.materiality.triggers}["allocation"] is False


def test_cash_plan_liquidity_trigger():
    plan = build_plan(demo_profile(), {"cash": 20000, "mf": 150000}, 170000)
    assert plan.liquidity_triggered  # 20K left < 25K buffer
    assert plan.gross == 170000 and plan.gap == 0


def test_plan_validation():
    plan = build_plan(demo_profile(), {"stocks": 90000}, 170000)
    assert plan.errors and plan.allocations["stocks"] == 80000 and plan.gap == 90000


def test_generalised_amount():
    p = demo_profile()
    r = WithdrawalRequest(50000, date(2026, 12, 1), "Medical")
    a = analyze(p, r, TODAY)
    assert pct(a.pct) == "6%"
    assert not a.materiality.triggers[0].triggered
    assert a.mf.total_cost == 1324 + 500  # 2.647% tax + 1% load, rounded
    assert a.borrow.interest_1y == 5000


def test_borrow_never_above_limit():
    p = demo_profile()
    a = analyze(p, WithdrawalRequest(300000, date(2026, 12, 1), "House / Property"), TODAY)
    assert not a.borrow.within_limit and a.borrow.borrowable == 250000 and a.borrow.remaining_room == 0


def test_validation_messages():
    p = demo_profile()
    assert validate(p, 0, date(2026, 12, 1), TODAY).errors["amount"] == "Enter an amount greater than ₹0."
    assert validate(p, 1000, date(2026, 1, 1), TODAY).errors["date"] == "Choose a future date for this prototype."
    v = validate(p, 600000, date(2026, 12, 1), TODAY)
    assert v.notices == ["₹6,00,000 cannot be fully funded from a single source in this demo."]


def test_formatting():
    assert inr(170000) == "₹1,70,000"
    assert inr(163800) == "₹1,63,800"
    assert inr(12345678) == "₹1,23,45,678"
    assert [inr_short(x) for x in (80000, 60000, 530000, 100000, 4500, 1700, 17000, 99000, 250000)] == \
        ["₹80K", "₹60K", "₹5.30L", "₹1.00L", "₹4.5K", "₹1.7K", "₹17K", "₹99K", "₹2.50L"]
