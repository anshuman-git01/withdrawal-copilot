"""Withdrawal Decision Copilot — FastAPI app (server-rendered, HTMX + Alpine)."""
from __future__ import annotations

import os
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import copilot, llm, store
from .engine import analyze
from .engine.formatting import inr, inr_short, nice_date, num, pct
from .engine.models import (ASSET_KEYS, ASSET_LABELS, REASONS, SOURCE_KEYS, Goal, current_allocation,
                            profile_from_dict, profile_to_dict, request_from_dict, request_to_dict, WithdrawalRequest)
from .engine.sources import build_plan, describe_plan


def _load_dotenv():
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

BASE = Path(__file__).resolve().parent
app = FastAPI(title="Withdrawal Decision Copilot", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
VENDOR = (BASE / "static" / "vendor").exists()
templates.env.globals.update(inr=inr, inr_short=inr_short, pct=pct, num=num, nice_date=nice_date,
                             ASSET_LABELS=ASSET_LABELS, ASSET_KEYS=ASSET_KEYS, SOURCE_KEYS=SOURCE_KEYS,
                             REASONS=REASONS, VENDOR=VENDOR)

COOKIE = "wc_sid"
STEPS = [("need", "Need"), ("understand", "Understand"), ("compare", "Compare"), ("decide", "Decide"),
         ("recover", "Recover")]
SCREEN_STEP = {"need": 1, "impact": 2, "goal": 2, "sources": 3, "borrow": 3, "decide": 4, "recover": 5}


def today() -> date:
    d = os.getenv("DEMO_TODAY")
    return date.fromisoformat(d) if d else date.today()


@app.middleware("http")
async def session_cookie(request: Request, call_next):
    sid = request.cookies.get(COOKIE)
    fresh = not sid or not re.fullmatch(r"[0-9a-f]{32}", sid)
    if fresh:
        sid = store.new_sid()
    request.state.sid = sid
    response = await call_next(request)
    if fresh:
        response.set_cookie(COOKIE, sid, max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax")
    return response


# ------------------------------------------------------------------ helpers

def S(request: Request) -> dict:
    return store.load(request.state.sid)


def save(request: Request, state: dict) -> None:
    store.save(request.state.sid, state)


def track(request: Request, state: dict, name: str, **props) -> None:
    store.track(request.state.sid, state, name, **props)


def ensure_attempt(request: Request, state: dict) -> None:
    if not state.get("attempt"):
        state["attempt"] = uuid.uuid4().hex[:12]
        state["first_amount"] = state["request"]["amount"]
        track(request, state, "withdrawal_started")
        save(request, state)


def get_plan(state: dict, profile, need: int):
    return build_plan(profile, state["plan"], need) if state.get("plan") else None


def analysis(state: dict):
    profile = profile_from_dict(state["profile"])
    req = request_from_dict(state["request"])
    return analyze(profile, req, today(), state.get("simulate_behaviour", False), get_plan(state, profile, req.amount))


def provider_of(state: dict) -> str:
    p = state.get("provider")
    return p if p in llm.PROVIDERS else llm.default_provider()


def render(request: Request, template: str, state: dict, screen: str = "", status_code: int = 200, **kw):
    a = kw.pop("a", None) or analysis(state)
    ctx = {
        "request": request, "a": a, "state": state, "screen": screen,
        "step": SCREEN_STEP.get(screen), "steps": STEPS,
        "presets": copilot.presets_for(screen or "impact", a),
        "providers": llm.status(), "provider": provider_of(state),
        "plan_text": describe_plan(a.plan) if a.plan else None,
        **kw,
    }
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)


def parse_money(v) -> Optional[int]:
    if v is None:
        return None
    s = re.sub(r"[^\d.\-]", "", str(v))
    if s in ("", "-", ".", "-."):
        return None
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def parse_float(v, default=0.0) -> float:
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


def parse_date(v) -> Optional[date]:
    try:
        return date.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# ------------------------------------------------------------------ top-level pages

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    state = S(request)
    return render(request, "screens/home.html", state, "home")


@app.get("/how-it-works", response_class=HTMLResponse)
async def how(request: Request):
    return render(request, "screens/how.html", S(request), "home")


@app.post("/reset")
async def reset(request: Request):
    store.save(request.state.sid, store.new_state())
    return redirect("/")


# ------------------------------------------------------------------ goals

@app.get("/goals", response_class=HTMLResponse)
async def goals(request: Request, saved: int = 0):
    state = S(request)
    return render(request, "screens/goals.html", state, "goal", saved=bool(saved))


@app.post("/goals/save")
async def goals_save(request: Request):
    state = S(request)
    form = await request.form()
    gid = str(form.get("id") or "").strip() or uuid.uuid4().hex[:8]
    td = parse_date(form.get("target_date"))
    g = Goal(
        id=gid,
        name=(str(form.get("name") or "").strip() or "Goal")[:40],
        category=str(form.get("category") or "Other"),
        target_amount=max(parse_money(form.get("target_amount")) or 0, 0),
        target_date=td or date(today().year + 3, 12, 31),
        saved_amount=max(parse_money(form.get("saved_amount")) or 0, 0),
        monthly_contribution=max(parse_money(form.get("monthly_contribution")) or 0, 0),
        expected_return_pct=parse_float(form.get("expected_return_pct"), 0.0),
    )
    goals_list = [x for x in state["profile"]["goals"] if x["id"] != gid]
    gd = {**g.__dict__, "target_date": g.target_date.isoformat()}
    existing_ids = [x["id"] for x in state["profile"]["goals"]]
    if gid in existing_ids:
        idx = existing_ids.index(gid)
        goals_list.insert(idx, gd)
    else:
        goals_list.append(gd)
    state["profile"]["goals"] = goals_list
    save(request, state)
    return redirect("/goals?saved=1")


@app.post("/goals/delete")
async def goals_delete(request: Request):
    state = S(request)
    form = await request.form()
    state["profile"]["goals"] = [g for g in state["profile"]["goals"] if g["id"] != form.get("id")]
    save(request, state)
    return redirect("/goals?saved=1")


# ------------------------------------------------------------------ settings / assumptions

@app.get("/settings", response_class=HTMLResponse)
async def settings(request: Request, saved: int = 0):
    state = S(request)
    profile = profile_from_dict(state["profile"])
    return render(request, "screens/settings.html", state, "home", saved=bool(saved),
                  current_alloc=current_allocation(profile.holdings))


@app.post("/settings")
async def settings_save(request: Request):
    state = S(request)
    f = await request.form()
    p = state["profile"]
    for k in ASSET_KEYS:
        p["holdings"][k] = max(parse_money(f.get(f"h_{k}")) or 0, 0)
    p["cash"] = max(parse_money(f.get("cash")) or 0, 0)
    p["liquidity_buffer"] = max(parse_money(f.get("liquidity_buffer")) or 0, 0)
    p["target_allocation"] = {k: parse_float(f.get(f"t_{k}"), p["target_allocation"].get(k, 0)) for k in ASSET_KEYS}
    a = p["assumptions"]
    for k in ("mf_tax_rate_pct", "mf_exit_load_pct", "fd_premature_pct", "stocks_friction_pct",
              "etfs_friction_pct", "borrow_rate_low_pct", "borrow_rate_high_pct"):
        a[k] = max(parse_float(f.get(k), a[k]), 0.0)
    if a["borrow_rate_high_pct"] < a["borrow_rate_low_pct"]:
        a["borrow_rate_high_pct"] = a["borrow_rate_low_pct"]
    a["borrow_limit"] = max(parse_money(f.get("borrow_limit")) or 0, 0)
    t = p["thresholds"]
    for k in ("portfolio_pct", "allocation_pp", "market_move_pct"):
        t[k] = max(parse_float(f.get(k), t[k]), 0.0)
    p["market_move_pct"] = parse_float(f.get("observed_market_move"), p.get("market_move_pct", 0.0))
    state["plan"] = None  # a stale plan could exceed new balances
    save(request, state)
    return redirect("/settings?saved=1")


@app.post("/settings/target-from-current")
async def target_from_current(request: Request):
    state = S(request)
    profile = profile_from_dict(state["profile"])
    state["profile"]["target_allocation"] = {k: round(v, 1) for k, v in current_allocation(profile.holdings).items()}
    save(request, state)
    return redirect("/settings?saved=1")


# ------------------------------------------------------------------ metrics

@app.get("/metrics", response_class=HTMLResponse)
async def metrics(request: Request, scope: str = "me"):
    state = S(request)
    m = store.metrics(None if scope == "all" else request.state.sid)
    return render(request, "screens/metrics.html", state, "home", m=m, scope=scope)


@app.post("/metrics/clear")
async def metrics_clear(request: Request):
    store.clear_events(request.state.sid)
    return redirect("/metrics")


ALLOWED_CLIENT_EVENTS = {"why_opened", "portfolio_impact_viewed"}


@app.post("/events/{name}")
async def client_event(request: Request, name: str):
    if name in ALLOWED_CLIENT_EVENTS:
        state = S(request)
        form = await request.form()
        track(request, state, name, topic=str(form.get("topic", ""))[:60])
    return Response(status_code=204)


# ------------------------------------------------------------------ withdrawal flow

@app.get("/withdraw")
async def withdraw_root():
    return redirect("/withdraw/need")


@app.get("/withdraw/start")
async def withdraw_start(request: Request):
    state = S(request)
    state.update({"attempt": None, "plan": None, "route": None, "decision": None, "simulate_behaviour": False})
    ensure_attempt(request, state)
    return redirect("/withdraw/need")


@app.get("/withdraw/need", response_class=HTMLResponse)
async def need(request: Request, focus: str = ""):
    state = S(request)
    ensure_attempt(request, state)
    a = analysis(state)
    return render(request, "screens/need.html", state, "need", a=a, form=state["request"], errors={},
                  notices=a.validation.notices, focus=focus)


def _read_need_form(form) -> tuple:
    amount = parse_money(form.get("amount"))
    d = parse_date(form.get("needed_by"))
    reason = str(form.get("reason") or "").strip() or None
    if reason and reason not in REASONS:
        reason = None
    return amount, d, reason


@app.post("/withdraw/need/preview", response_class=HTMLResponse)
async def need_preview(request: Request):
    state = S(request)
    form = await request.form()
    amount, d, reason = _read_need_form(form)
    from .engine.analysis import validate
    profile = profile_from_dict(state["profile"])
    v = validate(profile, amount, d, today())
    return templates.TemplateResponse(request, "partials/need_preview.html", {
        "request": request, "amount": amount, "needed_by": d, "reason": reason, "v": v,
        "pct_value": (amount / profile.holdings.total * 100) if amount and profile.holdings.total else None,
        "goals": profile.goals})


@app.post("/withdraw/need")
async def need_submit(request: Request):
    state = S(request)
    ensure_attempt(request, state)
    form = await request.form()
    amount, d, reason = _read_need_form(form)
    from .engine.analysis import validate
    profile = profile_from_dict(state["profile"])
    v = validate(profile, amount, d, today())
    if not v.ok:
        a = analysis(state)
        raw = {"amount": form.get("amount"), "needed_by": form.get("needed_by"), "reason": reason}
        return render(request, "screens/need.html", state, "need", a=a, form=raw, errors=v.errors,
                      notices=v.notices, status_code=422, focus="")
    prev = state["request"]["amount"]
    state["request"] = request_to_dict(WithdrawalRequest(amount, d, reason))
    track(request, state, "amount_entered", amount=amount)
    if reason:
        track(request, state, "reason_selected", reason=reason)
    if state.get("first_amount") is not None and amount != prev:
        track(request, state, "withdrawal_modified", from_amount=prev, to_amount=amount)
    state["plan"] = None
    state["route"] = None
    save(request, state)
    return redirect("/withdraw/impact")


@app.get("/withdraw/impact", response_class=HTMLResponse)
async def impact(request: Request):
    state = S(request)
    ensure_attempt(request, state)
    a = analysis(state)
    track(request, state, "impact_viewed")
    track(request, state, "portfolio_impact_viewed")
    if a.materiality.significant:
        track(request, state, "materiality_triggered", reasons=[t.key for t in a.materiality.reasons])
    if a.behaviour.triggered:
        track(request, state, "behaviour_check_triggered", simulated=a.behaviour.simulated)
    return render(request, "screens/impact.html", state, "impact", a=a)


def _behaviour_block(request, state, **kw):
    a = analysis(state)
    return templates.TemplateResponse(request, "partials/behaviour.html",
                                      {"request": request, "a": a, "state": state, **kw})


@app.post("/withdraw/behaviour/toggle", response_class=HTMLResponse)
async def behaviour_toggle(request: Request):
    state = S(request)
    state["simulate_behaviour"] = not state.get("simulate_behaviour", False)
    save(request, state)
    a = analysis(state)
    if a.behaviour.triggered:
        track(request, state, "behaviour_check_triggered", simulated=True)
    return _behaviour_block(request, state)


@app.post("/withdraw/behaviour/continue", response_class=HTMLResponse)
async def behaviour_continue(request: Request):
    state = S(request)
    track(request, state, "behaviour_check_continued")
    return _behaviour_block(request, state, acknowledged=True)


@app.post("/withdraw/behaviour/defer", response_class=HTMLResponse)
async def behaviour_defer(request: Request):
    state = S(request)
    track(request, state, "withdrawal_deferred", days=2)
    return _behaviour_block(request, state, deferred=True)


@app.get("/withdraw/smaller")
async def behaviour_smaller(request: Request):
    state = S(request)
    track(request, state, "withdrawal_modified", via="behaviour_check")
    return redirect("/withdraw/need?focus=amount")


@app.get("/withdraw/goal", response_class=HTMLResponse)
async def goal_impact(request: Request):
    state = S(request)
    ensure_attempt(request, state)
    track(request, state, "goal_impact_viewed")
    return render(request, "screens/goal_impact.html", state, "goal")


@app.get("/withdraw/sources", response_class=HTMLResponse)
async def sources(request: Request, full_only: int = 0):
    state = S(request)
    ensure_attempt(request, state)
    track(request, state, "source_comparison_viewed")
    return render(request, "screens/sources.html", state, "sources", full_only=bool(full_only))


@app.get("/withdraw/sources/table", response_class=HTMLResponse)
async def sources_table(request: Request, full_only: int = 0):
    state = S(request)
    a = analysis(state)
    return templates.TemplateResponse(request, "partials/sources_table.html",
                                      {"request": request, "a": a, "full_only": bool(full_only)})


def _mix_from_form(form) -> dict:
    return {k: parse_money(form.get(f"mix_{k}")) or 0 for k in SOURCE_KEYS}


@app.post("/withdraw/sources/mix", response_class=HTMLResponse)
async def sources_mix(request: Request):
    state = S(request)
    form = await request.form()
    profile = profile_from_dict(state["profile"])
    plan = build_plan(profile, _mix_from_form(form), state["request"]["amount"])
    return templates.TemplateResponse(request, "partials/mix_result.html",
                                      {"request": request, "plan": plan, "profile": profile})


@app.post("/withdraw/plan")
async def plan_save(request: Request):
    state = S(request)
    form = await request.form()
    single = form.get("source")
    if single in SOURCE_KEYS:
        profile = profile_from_dict(state["profile"])
        from .engine.sources import available
        mix = {single: min(state["request"]["amount"], available(profile, single))}
    else:
        mix = _mix_from_form(form)
    mix = {k: v for k, v in mix.items() if v > 0}
    state["plan"] = mix or None
    state["route"] = "sell" if mix else state.get("route")
    track(request, state, "funding_plan_chosen" if mix else "funding_plan_cleared", plan=mix)
    save(request, state)
    return redirect("/withdraw/borrow")


@app.post("/withdraw/plan/clear")
async def plan_clear(request: Request):
    state = S(request)
    state["plan"] = None
    save(request, state)
    return redirect("/withdraw/sources")


@app.get("/withdraw/borrow", response_class=HTMLResponse)
async def borrow(request: Request):
    state = S(request)
    ensure_attempt(request, state)
    track(request, state, "borrow_comparison_viewed")
    return render(request, "screens/borrow.html", state, "borrow")


@app.post("/withdraw/route")
async def route(request: Request):
    state = S(request)
    form = await request.form()
    r = form.get("route")
    state["route"] = r if r in ("sell", "borrow") else None
    save(request, state)
    return redirect("/withdraw/decide")


@app.get("/withdraw/decide", response_class=HTMLResponse)
async def decide(request: Request):
    state = S(request)
    ensure_attempt(request, state)
    return render(request, "screens/decide.html", state, "decide")


@app.post("/withdraw/decide")
async def decide_submit(request: Request):
    state = S(request)
    form = await request.form()
    action = form.get("action") if form.get("action") in ("withdraw", "borrow") else "withdraw"
    state["decision"] = {"action": action, "amount": state["request"]["amount"], "plan": state.get("plan")}
    track(request, state, "decision_completed", action=action, amount=state["request"]["amount"])
    save(request, state)
    return redirect("/withdraw/recover")


@app.get("/withdraw/recover", response_class=HTMLResponse)
async def recover(request: Request):
    state = S(request)
    if not state.get("decision"):
        return redirect("/withdraw/decide")
    return render(request, "screens/recover.html", state, "recover")


@app.get("/withdraw/recover/plan", response_class=HTMLResponse)
async def recover_plan(request: Request):
    state = S(request)
    if not state.get("decision"):
        # htmx would swap a followed redirect into the target; ask it to navigate instead
        if request.headers.get("HX-Request"):
            return Response(status_code=204, headers={"HX-Redirect": "/withdraw/decide"})
        return redirect("/withdraw/decide")
    track(request, state, "recovery_plan_viewed")
    a = analysis(state)
    return templates.TemplateResponse(request, "partials/recovery_plan.html", {
        "request": request, "a": a, "state": state, "plan_text": describe_plan(a.plan) if a.plan else None})


@app.post("/withdraw/recover/scenario", response_class=HTMLResponse)
async def recover_scenario(request: Request):
    state = S(request)
    form = await request.form()
    scen = str(form.get("scenario", ""))[:40]
    state["scenario"] = scen
    save(request, state)
    track(request, state, "recovery_scenario_selected", scenario=scen)
    return Response(status_code=204)


# ------------------------------------------------------------------ copilot

@app.post("/copilot/provider", response_class=HTMLResponse)
async def copilot_provider(request: Request):
    state = S(request)
    form = await request.form()
    p = form.get("provider")
    if p in llm.PROVIDERS:
        state["provider"] = p
        save(request, state)
    return templates.TemplateResponse(request, "partials/provider.html",
                                      {"request": request, "providers": llm.status(), "provider": provider_of(state)})


@app.post("/copilot/ask", response_class=HTMLResponse)
async def copilot_ask(request: Request):
    state = S(request)
    form = await request.form()
    screen = str(form.get("screen") or "impact")
    a = analysis(state)
    facts = copilot.facts(a)
    qid = form.get("qid") if form.get("qid") in copilot.PRESETS else None
    text = str(form.get("text") or "").strip()[:500]
    if qid:
        question = copilot.preset_label(qid, a)
    else:
        question = text
        qid = copilot.match_question(text) if text else None
    if not question:
        return Response(status_code=204)

    fallback = copilot.scripted(qid, a) if qid else (
        "I explain the numbers behind this withdrawal: the portfolio impact, goal trajectory, illustrative costs, "
        "source comparison and borrowing figures. That question isn't estimated in this prototype.")
    provider = provider_of(state)
    note, source = None, "Scripted explanation from engine outputs"
    answer = fallback
    if provider != "offline":
        try:
            raw = await llm.complete(provider, copilot.SYSTEM_PROMPT, copilot.build_user_prompt(question, facts, screen))
            ok, why = copilot.check_answer(raw, facts)
            if ok and raw:
                answer, source = raw, f"Answered by {llm.PROVIDERS[provider]['label']} from engine outputs"
            else:
                note = f"The {llm.PROVIDERS[provider]['label']} answer {why}, so the engine's scripted explanation is shown."
                track(request, state, "copilot_fallback", reason=why)
        except llm.LLMError as e:
            note = f"{e}. Showing the engine's scripted explanation."
            track(request, state, "copilot_fallback", reason=str(e))
    track(request, state, "copilot_asked", qid=qid or "free_text", provider=provider)
    if qid in ("significant", "pct"):
        track(request, state, "why_opened", topic=f"copilot:{qid}")
    return templates.TemplateResponse(request, "partials/copilot_answer.html", {
        "request": request, "question": question, "answer": answer, "note": note, "source": source})


@app.post("/copilot/test", response_class=HTMLResponse)
async def copilot_test(request: Request):
    results = [await llm.test_provider(p) for p in ("gemini", "groq")]
    return templates.TemplateResponse(request, "partials/ai_test.html", {"request": request, "results": results})


@app.get("/healthz")
async def healthz():
    return {"ok": True}
