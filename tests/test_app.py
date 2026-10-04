"""End-to-end flow through the real FastAPI app (runs on your machine)."""
import os
import tempfile

import pytest

pytest.importorskip("fastapi")
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DEMO_TODAY"] = "2026-10-04"
os.environ["LLM_PROVIDER"] = "offline"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def c():
    return TestClient(app)


def test_presenter_flow(c):
    r = c.get("/")
    assert r.status_code == 200 and "₹7,70,000" in r.text and "₹40,000" in r.text and "₹8,10,000" not in r.text
    assert c.get("/withdraw/start").status_code == 200
    r = c.post("/withdraw/need", data={"amount": "1,70,000", "needed_by": "2026-11-30", "reason": "House / Property"},
               follow_redirects=False)
    assert r.status_code == 303
    r = c.get("/withdraw/impact")
    assert "This withdrawal is 22% of your invested portfolio and affects your House goal." in r.text
    assert "Not triggered" in r.text and "₹6.2K" in r.text and "₹1.638L" in r.text
    r = c.post("/withdraw/behaviour/toggle")
    assert "Markets fell 6% this week. Is this withdrawal related?" in r.text and "Continue" in r.text
    c.post("/withdraw/behaviour/toggle")
    assert "Scenarios, not recommendations." in c.get("/withdraw/goal").text
    r = c.get("/withdraw/sources")
    assert "₹1.638L" in r.text and "₹99K" in r.text
    r = c.get("/withdraw/borrow")
    assert "₹2,50,000" in r.text and "₹80,000" in r.text and "9–11% p.a." in r.text and "₹17,000" in r.text
    r = c.post("/copilot/ask", data={"qid": "significant", "screen": "impact"})
    assert "about 22%" in r.text
    r = c.post("/withdraw/decide", data={"action": "withdraw"}, follow_redirects=False)
    assert r.status_code == 303
    r = c.get("/withdraw/recover")
    assert "Decision recorded" in r.text and "Scenarios, not recommendations." in r.text
    m = c.get("/metrics").text
    assert "100%" in m


def test_validation(c):
    r = c.post("/withdraw/need", data={"amount": "0", "needed_by": "2026-01-01", "reason": ""})
    assert r.status_code == 422
    assert "Enter an amount greater than ₹0." in r.text and "Choose a future date for this prototype." in r.text


def test_plan_and_mix(c):
    c.post("/withdraw/need", data={"amount": "170000", "needed_by": "2026-11-30", "reason": "House / Property"})
    r = c.post("/withdraw/sources/mix", data={"mix_mf": "1,50,000", "mix_cash": "20,000"})
    assert "below your ₹25,000 buffer" in r.text
    c.post("/withdraw/plan", data={"source": "mf"})
    assert "Allocation moves 8.8 points" in c.get("/withdraw/decide").text


def test_recovery_plan_without_decision_redirects(c):
    c.post("/reset")
    r = c.get("/withdraw/recover/plan", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/withdraw/decide"
    r = c.get("/withdraw/recover/plan", headers={"HX-Request": "true"})
    assert r.status_code == 204 and r.headers["HX-Redirect"] == "/withdraw/decide"
