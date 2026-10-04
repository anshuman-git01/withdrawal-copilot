"""Copilot answers come from engine outputs; the guardrail blocks invented numbers."""
from datetime import date

from app.copilot import PRESETS, check_answer, facts, match_question, scripted
from app.engine import analyze, demo_profile, demo_request

A = analyze(demo_profile(), demo_request(), date(2026, 10, 4))
F = facts(A)


def test_spec_example_answer():
    s = scripted("significant", A)
    assert "₹1.70L from a ₹7.70L invested portfolio" in s
    assert "about 22%" in s and "10% portfolio-impact threshold" in s
    assert "House goal is affected" in s


def test_every_scripted_answer_passes_guardrail():
    for qid in PRESETS:
        ok, why = check_answer(scripted(qid, A), F)
        assert ok, (qid, why)


def test_guardrail_accepts_engine_numbers():
    ok, _ = check_answer("You receive ₹1,63,800 after ₹6.2K of mock deductions, 22% of ₹7.70L. Rate 9–11% p.a., "
                         "₹17,000 at 10%.", F)
    assert ok


def test_guardrail_blocks_invented_numbers():
    assert not check_answer("Your EMI would be ₹14,950 a month.", F)[0]
    assert not check_answer("That's about 35% of your portfolio.", F)[0]
    assert not check_answer("It's roughly 3.2 lakh.", F)[0]


def test_guardrail_blocks_recommendations():
    assert not check_answer("Borrowing is better here.", F)[0]
    assert not check_answer("You should stay invested.", F)[0]


def test_free_text_matching():
    assert match_question("how is 22% calculated") == "pct"
    assert match_question("why do I get less than 1.7L from MF, is it exit load?") == "mf_received"
    assert match_question("what about my house") == "goal"
