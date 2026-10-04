"""Deterministic financial engine. The LLM layer never computes values; it explains these outputs."""
from .analysis import Analysis, analyze, validate  # noqa: F401
from .models import demo_profile, demo_request  # noqa: F401
