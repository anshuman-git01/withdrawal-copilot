"""Copilot explanation layer.

Pipeline: verified data -> deterministic engine -> materiality -> scenarios ->
LLM explanation -> user decides.

The LLM receives only engine outputs (facts). Its answer is checked: every
rupee figure and percentage it mentions must exist in the facts, and it must
not use recommendation language. Otherwise the scripted answer is shown.
"""
from __future__ import annotations

import json
import re

from .engine.analysis import Analysis
from .engine.formatting import inr, inr_short, nice_date, num, pct

PRESETS = {
    "significant": "Why is this significant?",
    "pct": "How did you calculate 22%?",
    "goal": "What happens to my House goal?",
    "mf_received": "Why does the MF amount received differ from ₹1.70L?",
    "borrow_limit": "What does the borrowing limit mean?",
    "behaviour": "Why didn't the behaviour check appear?",
    "compare": "How do the sources compare?",
    "sell_vs_borrow": "How do selling and borrowing differ here?",
    "recover": "What are my recovery scenarios?",
}

SCREEN_PRESETS = {
    "home": ["significant", "borrow_limit"],
    "need": ["significant", "pct"],
    "impact": ["significant", "pct", "mf_received", "behaviour"],
    "goal": ["goal", "recover"],
    "sources": ["compare", "mf_received"],
    "borrow": ["sell_vs_borrow", "borrow_limit"],
    "decide": ["significant", "goal"],
    "recover": ["recover", "goal"],
}

BANNED = [
    "you should", "i recommend", "we recommend", "i'd recommend", "i would recommend", "best option",
    "better option", "is better", "is cheaper", "don't withdraw", "do not withdraw", "stay invested",
    "bad decision", "guaranteed", "you must",
]


def preset_label(qid: str, a: Analysis) -> str:
    """Preset questions use the live numbers, not the demo ones."""
    g = a.primary_goal
    labels = dict(PRESETS)
    labels["pct"] = f"How did you calculate {pct(a.pct)}?"
    labels["mf_received"] = f"Why does the MF amount received differ from {inr_short(a.request.amount)}?"
    labels["goal"] = f"What happens to my {g.goal.name} goal?" if g else "What happens to my goals?"
    return labels[qid]


def presets_for(screen: str, a: Analysis) -> list:
    return [(q, preset_label(q, a)) for q in SCREEN_PRESETS.get(screen, SCREEN_PRESETS["impact"])]


# ------------------------------------------------------------------ facts

def facts(a: Analysis) -> dict:
    g = a.primary_goal
    mf = a.mf
    b = a.borrow
    return {
        "request": {"amount": inr(a.request.amount), "amount_short": inr_short(a.request.amount),
                    "needed_by": nice_date(a.request.needed_by), "reason": a.request.reason or "Not selected"},
        "invested_portfolio": inr(a.invested),
        "invested_breakdown": {s.label: inr(s.available) for s in a.sources if s.key != "cash"},
        "accessible_cash": inr(a.cash) + " (not part of the invested portfolio)",
        "portfolio_impact": f"{inr(a.request.amount)} ÷ {inr(a.invested)} = {num(a.pct, 2)}%, shown as {pct(a.pct)}",
        "materiality": {
            "significant": a.materiality.significant,
            "rule": "Significant if ANY trigger is true. No score.",
            "triggers": [{"name": t.name, "triggered": t.triggered, "detail": t.detail}
                         for t in a.materiality.triggers],
            "thresholds": {
                "portfolio": f"{num(a.profile.thresholds.portfolio_pct)}% or more",
                "allocation": f"more than {num(a.profile.thresholds.allocation_pp)} percentage points",
                "liquidity_buffer": inr(a.profile.liquidity_buffer),
            },
        },
        "goal": None if not g else {
            "name": g.goal.name, "status_before": g.status_before, "status_after": g.status_after,
            "target": inr(g.goal.target_amount), "target_date": nice_date(g.goal.target_date),
            "projected_before": inr(g.projected_before), "projected_after": inr(g.projected_after),
            "gap_after": inr(g.gap_after),
            "scenario_extra_monthly": inr(g.extra_monthly_needed) if g.extra_monthly_needed else None,
            "scenario_extension_months": g.extension_months,
            "note": "Projections use the user's own goal inputs and assumed return. Scenarios, not recommendations.",
        },
        "mutual_fund_withdrawal": {
            "costs": {label: inr(v) for label, v in mf.costs}, "total_deductions": inr(mf.total_cost),
            "estimated_received": inr(mf.received), "settlement": mf.settlement,
            "label": "Illustrative mock estimate — not a tax or transaction quote.",
        },
        "sources": [{"source": s.label, "available": inr(s.available), "status": s.status,
                     "cost": inr(s.total_cost), "received": inr(s.received), "settlement": s.settlement,
                     "allocation_shift_points": num(s.allocation_pp, 1)} for s in a.sources],
        "borrowing": {
            "eligible_limit": inr(b.limit), "need": inr(b.need), "within_limit": b.within_limit,
            "remaining_room": inr(b.remaining_room), "indicative_rate": b.rate_band,
            "illustrative_midpoint": f"{num(b.rate_mid)}% p.a.",
            "illustrative_1y_interest": f"{inr(b.interest_1y)} on {inr(b.borrowable)}",
            "collateral": b.collateral, "note": "Pledged assets remain pledged until repayment.",
            "label": "Illustrative comparison — not financial advice or a lender quote.",
        },
        "behaviour_check": {
            "triggered": a.behaviour.triggered, "simulated": a.behaviour.simulated,
            "rule": f"Fires only when market movement is {num(a.profile.thresholds.market_move_pct)}% or more AND the reason is Other or blank.",
            "status": a.behaviour.status_copy,
        },
    }


# ------------------------------------------------------------------ scripted answers

def scripted(qid: str, a: Analysis) -> str:
    g = a.primary_goal
    amt, inv = inr_short(a.request.amount), inr_short(a.invested)
    if qid == "significant":
        if not a.materiality.significant:
            return (f"You're withdrawing {amt} from a {inv} invested portfolio, about {pct(a.pct)}. That is below the "
                    f"{num(a.profile.thresholds.portfolio_pct)}% portfolio-impact threshold, and no other trigger is met, "
                    "so it isn't treated as significant. You still see the full picture.")
        parts = []
        for t in a.materiality.reasons:
            if t.key == "portfolio":
                parts.append(f"You're withdrawing {amt} from a {inv} invested portfolio. That's about {pct(a.pct)}, "
                             f"which is above the {num(a.profile.thresholds.portfolio_pct)}% portfolio-impact threshold used in this prototype.")
            elif t.key == "goal":
                parts.append(f"{t.reason_copy}.")
            else:
                parts.append(f"{t.reason_copy}.")
        return " ".join(parts) + " Any one trigger is enough, so the withdrawal is treated as significant. There's no score involved."
    if qid == "pct":
        return (f"{inr(a.request.amount)} withdrawal ÷ {inr(a.invested)} invested portfolio = {num(a.pct, 2)}%, shown as "
                f"{pct(a.pct)}. Your {inr(a.cash)} accessible cash is kept separate and isn't counted as invested portfolio.")
    if qid == "goal":
        if not g:
            return "You don't have a tracked goal yet, so no goal is affected. You can add one on the Goals page."
        if not g.affected:
            return f"Your {g.goal.name} goal stays {g.status_before.lower()}; this withdrawal doesn't draw on it."
        s = (f"Your {g.goal.name} goal is {g.status_before.lower()} today. After withdrawing {amt}, it moves to "
             f"'{g.status_after.lower()}'. Based on your goal inputs, the projected value at "
             f"{nice_date(g.goal.target_date)} goes from {inr(g.projected_before)} to {inr(g.projected_after)} "
             f"against a {inr(g.goal.target_amount)} target.")
        if g.triggered:
            s += " See the recovery scenarios for ways to close that gap. They're scenarios, not recommendations."
        return s
    if qid == "mf_received":
        costs = " and ".join(f"{inr(v)} {label.lower()}" for label, v in a.mf.costs)
        return (f"Withdrawing {inr(a.mf.draw)} from Mutual Funds includes {costs}, a total of {inr(a.mf.total_cost)} in "
                f"illustrative deductions. {inr(a.mf.draw)} − {inr(a.mf.total_cost)} = {inr(a.mf.received)} estimated "
                "amount received. These are mock estimates, not a tax or transaction quote.")
    if qid == "borrow_limit":
        b = a.borrow
        s = (f"The eligible borrowing limit is the most you could borrow against eligible investments in this prototype: "
             f"{inr(b.limit)}. ")
        if b.within_limit:
            s += f"Your need of {inr(b.need)} is within it, leaving {inr(b.remaining_room)} of room. "
        else:
            s += f"Your need of {inr(b.need)} is above it, so only {inr(b.borrowable)} is shown. "
        s += (f"At the illustrative {num(b.rate_mid)}% midpoint of the {b.rate_band} band, one year of interest on "
              f"{inr(b.borrowable)} is {inr(b.interest_1y)}. Pledged assets stay pledged until repayment. "
              "Actual terms depend on the lender.")
        return s
    if qid == "behaviour":
        bc = a.behaviour
        if bc.triggered:
            return (f"{bc.message} The check fires only when markets move "
                    f"{num(a.profile.thresholds.market_move_pct)}% or more and the reason is Other or not given. "
                    "Continue is always available.")
        return (f"The behaviour check needs two things at once: a market move of "
                f"{num(a.profile.thresholds.market_move_pct)}% or more, and a reason of Other or none. You selected "
                f"'{bc.reason}'. {bc.status_copy}")
    if qid == "compare":
        lines = []
        for s in a.sources:
            lines.append(f"{s.label}: {inr(s.available)} available, {inr(s.total_cost)} illustrative cost, "
                         f"{inr(s.received)} received ({s.status.lower()})")
        full = [s.label for s in a.full_cover_sources]
        tail = (f" Only {', '.join(full)} can cover {amt} alone; the others can be combined by you."
                if full else " No single source covers the full amount; you can combine them yourself.")
        return "; ".join(lines) + "." + tail
    if qid == "sell_vs_borrow":
        b = a.borrow
        return (f"Withdrawing {amt} from Mutual Funds has {inr(a.mf.total_cost)} in illustrative deductions and "
                f"reduces your invested portfolio by {pct(a.pct)}. Borrowing keeps investments in place but pledged, "
                f"with about {inr(b.interest_1y)} illustrative interest for a year at {num(b.rate_mid)}%. Neither is "
                "automatically better; it depends on your liquidity, goal, costs and repayment ability.")
    if qid == "recover":
        if not g or not g.triggered:
            return "No tracked goal falls below its trajectory, so there's nothing to recover."
        opts = []
        if g.extra_monthly_needed:
            opts.append(f"add about {inr(g.extra_monthly_needed)} a month")
        if g.extension_months:
            opts.append(f"reach the goal about {g.extension_months} month{'s' if g.extension_months != 1 else ''} later")
        opts.append(f"keep {inr(g.goal.monthly_contribution)} a month and accept a projected {inr(g.projected_after)}")
        return (f"Based on your {g.goal.name} goal inputs, you could " + ", or ".join(opts) +
                ". These are scenarios, not recommendations.")
    return "I can explain the numbers on this screen. Try one of the suggested questions."


KEYWORDS = [
    ("pct", ["calculate", "22", "percent", "%", "how is"]),
    ("mf_received", ["receive", "received", "differ", "exit load", "tax", "deduction"]),
    ("borrow_limit", ["limit", "eligible", "pledge", "loan", "interest"]),
    ("sell_vs_borrow", ["borrow", "sell vs", "selling"]),
    ("behaviour", ["behaviour", "behavior", "market", "panic"]),
    ("recover", ["recover", "scenario", "catch up", "extend"]),
    ("goal", ["goal", "house", "trajectory"]),
    ("compare", ["source", "compare", "fd", "stocks", "etf", "cash"]),
    ("significant", ["significant", "why", "trigger", "material"]),
]


def match_question(text: str):
    t = text.lower()
    for qid, kws in KEYWORDS:
        if any(k in t for k in kws):
            return qid
    return None


# ------------------------------------------------------------------ guardrails

_UNITS = {"l": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "k": 1e3, "cr": 1e7, "crore": 1e7, "crores": 1e7}
RUPEE_RE = re.compile(r"(?:₹|rs\.?|inr)\s?([\d,]+(?:\.\d+)?)\s?(lakhs?|lac|crores?|cr|l|k)?\b", re.I)
LAKH_RE = re.compile(r"(?<![₹\d.,])([\d]+(?:\.\d+)?)\s?(lakhs?|crores?)\b", re.I)
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?%")


def _rupee_values(text: str) -> list:
    out = []
    for m in RUPEE_RE.finditer(text):
        v = float(m.group(1).replace(",", ""))
        if m.group(2):
            v *= _UNITS[m.group(2).lower()]
        out.append(v)
    for m in LAKH_RE.finditer(text):
        out.append(float(m.group(1)) * _UNITS[m.group(2).lower()])
    return out


def allowed_numbers(f: dict) -> tuple:
    blob = json.dumps(f, ensure_ascii=False)
    rupees = set(_rupee_values(blob))
    pcts = {float(x) for x in PCT_RE.findall(blob)}
    # band endpoints like "9–11% p.a." expose only 11 to the regex
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s?[–-]\s?(\d+(?:\.\d+)?)%", blob):
        pcts.update({float(m.group(1)), float(m.group(2))})
    for m in re.finditer(r"([\d.]+) percentage points|\"allocation_shift_points\": \"([\d.]+)\"", blob):
        pcts.update(float(x) for x in m.groups() if x)
    return rupees, pcts


def check_answer(answer: str, f: dict) -> tuple:
    """Return (ok, problem). ok=False means fall back to the scripted answer."""
    low = answer.lower()
    for phrase in BANNED:
        if phrase in low:
            return False, f"used recommendation language ('{phrase}')"
    rupees, pcts = allowed_numbers(f)
    for v in _rupee_values(answer):
        if not any(abs(v - r) <= max(0.006 * r, 1) for r in rupees):
            return False, f"mentioned a figure the engine did not produce ({inr(v)})"
    for p in (float(x) for x in PCT_RE.findall(answer)):
        tol = 0.55 if p == int(p) else 0.06
        if not any(abs(p - q) <= tol for q in pcts):
            return False, f"mentioned a percentage the engine did not produce ({num(p)}%)"
    return True, ""


SYSTEM_PROMPT = """You are Withdrawal Copilot, an explanation layer inside an investment-withdrawal decision tool.
You explain numbers that a deterministic engine has already calculated. You are given those numbers as FACTS (JSON).

Rules:
- Use ONLY figures that appear in FACTS. Never calculate, estimate, round differently or invent any new number.
- Never predict markets, never recommend a product or source, never say one option is better or cheaper.
- Never discourage the withdrawal. The user decides. Use neutral words: "here's what changes", "illustrative", "you decide".
- Label costs as illustrative mock estimates, and borrowing as illustrative, not a lender quote.
- If the question asks for something not in FACTS, say it is not estimated in this prototype.
- Plain English, 2 to 5 sentences, no headings, no bullet lists. Use the ₹ formats exactly as written in FACTS."""


def build_user_prompt(question: str, f: dict, screen: str) -> str:
    return f"Screen: {screen}\nFACTS:\n{json.dumps(f, ensure_ascii=False, indent=1)}\n\nQuestion: {question}"
