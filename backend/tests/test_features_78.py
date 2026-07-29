"""Features 7–8 unit smoke tests."""

from __future__ import annotations

import pytest

from app.intelligence.psychological_profiler import build_profile
from app.intelligence.message_writer import _fallback_formats, FORMATS


def test_build_profile_structure():
    voter = {
        "id": "42",
        "first_name": "דרור",
        "last_name": "כהן",
        "neighborhood": "נווה עוז",
        "city": "פתח תקווה",
        "gotv_category": "SWING",
        "support_score": 0.55,
        "turnout_history": 0.6,
        "enriched_at": "2026-01-01T00:00:00Z",
    }
    result = build_profile(voter)
    assert result["voter_id"] == "42"
    assert 1 <= result["profile"]["socio_economic"]["tier"] <= 10
    bf = result["profile"]["personality"]["big_five"]
    for k in ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"):
        assert 0.0 <= bf[k] <= 1.0
    assert result["confidence"] > 0.5
    assert 0.0 <= result["profile"]["loyalty"]["loyalty_score"] <= 1.0


def test_fallback_formats_hebrew_and_length():
    psych = build_profile(
        {
            "id": "1",
            "first_name": "יוסי",
            "last_name": "לוי",
            "neighborhood": "מרכז העיר",
            "gotv_category": "SAFE",
            "support_score": 0.8,
            "turnout_history": 0.7,
        }
    )
    formats = _fallback_formats(
        first="יוסי",
        full_name="יוסי לוי",
        neighborhood="מרכז העיר",
        gotv="SAFE",
        topic="חינוך",
        psych=psych,
    )
    assert set(formats.keys()) == set(FORMATS)
    assert len(formats["social_post_x"]["text"]) <= 280
    for fmt, item in formats.items():
        assert item["engagement_score"] > 0.5
        assert any("\u0590" <= ch <= "\u05FF" for ch in item["text"])
