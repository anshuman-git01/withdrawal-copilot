# Withdrawal Decision Copilot

> Tell us what you need. Before you take the money, see what it changes.

A need-first decision layer that sits *before* an investment withdrawal. It shows the impact on your portfolio, goals, liquidity and costs, compares every funding source and borrowing, and then lets you decide. It never blocks, never auto-sells, never recommends.

**Demo mode:** no real money moves and no login is needed. Every figure is illustrative.

---

## Run it (5 minutes)

**Requirements:** Python 3.10+.

```bash
# macOS / Linux
./run.sh
# Windows
run.bat
```

Then open **http://localhost:8000**.

`run.sh` / `run.bat` do three things: create a virtualenv, install `requirements.txt`, and copy `.env.example` to `.env`.

Manual setup instead:
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

### Turn on the AI Copilot (free)
See **Turn on Gemini and Groq** below. With no key, or if a call fails, Copilot falls back to scripted explanations built from the same engine outputs, so the demo never breaks on stage.

### Fully offline demo (recommended before presenting)
```bash
python scripts/vendor_assets.py   # run once while online
```
This stores HTMX and Alpine locally. CSS is already precompiled, so the app then needs no internet at all (Copilot uses scripted answers offline). Fonts fall back to system fonts.

### Run the tests
```bash
pytest
```
- `tests/test_engine.py` is the spec's Section 39 checklist as code: every canonical value, trigger state and rule.
- `tests/test_copilot.py` checks that the guardrail blocks invented numbers and recommendation language.
- `tests/test_app.py` runs the full presenter flow through the real app.
- `tests/test_llm.py` checks provider fallbacks and missing-key handling without network calls.

---

## Presenter script (no typing needed)

The app starts in the exact demo state: ₹7.70L invested, ₹40K accessible cash, need ₹1.70L by 30 Nov 2026 for House / Property, behaviour toggle off.

1. **Portfolio:** ₹7,70,000 invested and ₹40,000 accessible cash, shown separately. Click **I need money**.
2. **What do you need?** The form is prefilled. Click **See what changes**.
3. **Before you confirm:**
   - Show 22% (open *How is this calculated?*), *Significant withdrawal* with its two reasons, and ₹6.2K illustrative MF deductions.
   - Show Behaviour check: *Not triggered*.
   - Optional: flip **Simulate market behaviour check**. "Markets fell 6% this week…" appears, and Continue is always available. Flip it back off.
4. **See goal impact:** before/after trajectory and three recovery scenarios.
5. **Compare funding options:**
   - All five sources side by side.
   - Tick *only sources that can fully cover*; only Mutual Funds remain.
   - Note MF's 8.8-point allocation move.
   - Optionally build a split in **Choose how to fund**.
6. **Compare sell vs borrow:** ₹2.50L limit, ₹80K room, 9–11% p.a., ₹17,000 illustrative interest. Open **Explore borrowing** for detail.
7. **Go to decision:** full summary, then **Withdraw ₹1.70L**.
8. **Recover:** *Decision recorded*, then scenarios, then **View my recovery plan**.
9. **Ask Copilot** (top right) on any screen. Try "Why is this significant?"
10. **⋯ menu, then Metrics:** north-star rate and the event log from your walkthrough.

To restart: **⋯ menu, then Reset to demo data**.

> **Date note:** the demo date is 30 Nov 2026. After that date passes, set `DEMO_TODAY=2026-10-04` in `.env` so the demo still validates.

---

## Architecture

```
Verified financial data      app/engine/models.py      holdings, cash, goals, settings
        ↓
Deterministic engine         app/engine/sources.py     costs, amounts received, allocation
                             app/engine/borrow.py      borrowing figures, behaviour check
        ↓
Materiality engine           app/engine/analysis.py    4 OR-triggers, no score
        ↓
Scenario engine              app/engine/goals.py       trajectories, recovery scenarios
        ↓
LLM explanation layer        app/copilot.py + llm.py   Gemini / Groq explain facts only
        ↓
User decides                 app/main.py + templates   7 screens, nothing auto-executed
```

**The LLM never calculates.** It receives the engine's outputs as JSON facts. Every answer passes a guardrail:
- Every ₹ figure and percentage in the answer must exist in the facts (with rounding tolerance).
- Phrases like "you should", "is better" and "stay invested" are rejected.

A failing answer is replaced by the scripted explanation and logged as `copilot_fallback`.

| Layer | Choice |
|---|---|
| Server | FastAPI + Uvicorn |
| UI | Jinja2 templates, HTMX (partial updates), Alpine.js (toggles, modals), Tailwind CSS (precompiled to `app/static/app.css`) |
| Engine | Pure Python standard library (dataclasses), fully unit-tested |
| Storage | SQLite (`data/app.db`): per-browser session state and analytics events |
| AI | Gemini and Groq over HTTPS via httpx, switchable at runtime |

### Generalised beyond the demo
- **Inputs:** any amount, date or reason. Every value recalculates.
- **Portfolio & assumptions** page (⋯ menu): holdings, cash, liquidity buffer, target allocation, mock cost rates, borrowing limit and rate band, and all thresholds are editable.
- **Goals** page: add or edit goals (target, date, amount saved, monthly contribution, assumed return, linked reason).

**How a withdrawal reduces a goal:**
- If the withdrawal reason matches the goal's linked reason, it draws on that goal's corpus.
- Otherwise every goal is reduced in proportion to the share of the portfolio withdrawn.

**Where each trigger is checked:**
- **Screen 3** evaluates materiality source-agnostically, so allocation and liquidity are unchanged.
- **Compare and Decide** re-evaluate all four triggers against the actual source or split you choose.

### Demo seed values not fixed by the brief
These are editable and marked as user inputs:

| Input | Seed value | Effect |
|---|---|---|
| House goal | ₹24L by Dec 2030, ₹6L saved, ₹25K a month, 10% assumed return | On track before the withdrawal, below trajectory after |
| Liquidity buffer | ₹25,000 | — |
| Target allocation | Current allocation | — |
| MF mock tax | 2.6471% of the amount withdrawn | ₹4,500 on ₹1,70,000, exactly as specified |

### Restyling
Design tokens live in `tailwind.config.js` (matched to the FinLit Ventures × ProduScope deck: orange #DD4B2B, off-white #F0EEE9, charcoal #2B2B2B; Inter + Inter Tight). After editing templates or tokens, rebuild the CSS:
```bash
npm install && npm run build:css
```

---

## Turn on Gemini and Groq

1. Get free keys (no credit card needed):
   - **Gemini:** https://aistudio.google.com/apikey → *Create API key*
   - **Groq:** https://console.groq.com/keys → *Create API key*
2. Paste them into `.env` (local) or your host's environment variables:
   ```
   GEMINI_API_KEY=your-gemini-key
   GROQ_API_KEY=your-groq-key
   ```
3. Restart the server. Open **⋯ menu, then Portfolio & assumptions**, and click **Test AI connection**. Each provider shows *Working* with the model it used, or the exact reason it isn't working.
4. In any screen, open **Ask Copilot** and switch providers with the **Explained by** dropdown.

**Models.** Leave `GEMINI_MODEL` / `GROQ_MODEL` blank to use the built-in fallback chains:

| Provider | Tried in this order |
|---|---|
| Gemini | `gemini-flash-latest` (Google's rolling alias) → `gemini-2.5-flash` → `gemini-2.5-flash-lite` |
| Groq | `openai/gpt-oss-120b` → `openai/gpt-oss-20b` |

If a model is retired, the app moves to the next one automatically. Groq retired the Llama 3.x models on 16 Aug 2026, which is why they aren't in the chain.

**Free-tier limits.** Both providers rate-limit free keys. If you hit a limit mid-demo, Copilot says so and shows the scripted explanation instead, so the demo keeps working.

---

## Deploy (free, about 10 minutes)

### 1. Put the code on GitHub
Create an empty repository named `withdrawal-copilot` on GitHub (no README). Then, inside the project folder:
```bash
git init
git add .
git commit -m "Withdrawal Decision Copilot"
git branch -M main
git remote add origin https://github.com/<your-username>/withdrawal-copilot.git
git push -u origin main
```
`.env` is in `.gitignore`, so your keys are never pushed.

### 2. Deploy on Render (free)
1. Sign in at https://render.com with GitHub.
2. Click **New**, then **Blueprint**, and pick the `withdrawal-copilot` repo. Render reads `render.yaml`.
3. When asked, paste your `GEMINI_API_KEY` and `GROQ_API_KEY`, then click **Apply**.
4. Wait for the first build (about 3–5 minutes). Your link looks like `https://withdrawal-copilot-xxxx.onrender.com`.
5. Open the link, go to **⋯ menu, then Portfolio & assumptions**, and click **Test AI connection**.

`render.yaml` pins `DEMO_TODAY=2026-10-04` so the 30 Nov 2026 demo date stays valid. Remove it in Render's *Environment* tab to use the real date.

**Before you present:** free Render services sleep after about 15 minutes idle and take about a minute to wake. Open the link 2 minutes before your slot. Saved sessions and metrics reset on each redeploy or wake; that's fine for a demo.

### Other hosts
- **Railway:** *New project*, then *Deploy from GitHub repo*. The Dockerfile is detected; add the two keys under *Variables*.
- **Any server with Docker:** `docker build -t copilot . && docker run -p 8000:8000 --env-file .env copilot`

## Analytics events
Tracked events:

| Stage | Events |
|---|---|
| Start and inputs | `withdrawal_started`, `amount_entered`, `reason_selected` |
| Understanding | `materiality_triggered`, `impact_viewed`, `portfolio_impact_viewed`, `goal_impact_viewed`, `why_opened` |
| Comparing | `source_comparison_viewed`, `borrow_comparison_viewed`, `funding_plan_chosen` |
| Behaviour check | `behaviour_check_triggered`, `behaviour_check_continued`, `withdrawal_modified`, `withdrawal_deferred` |
| Decision and recovery | `decision_completed`, `recovery_plan_viewed`, `recovery_scenario_selected` |
| Copilot | `copilot_asked`, `copilot_fallback` |

**North Star:** significant attempts that viewed the impact screen *and* reached a decision ÷ all significant attempts. Whatever the decision was, it counts.

---

*Illustrative prototype for a case competition. Not financial advice, not a tax or lender quote. No transactions are executed.*
