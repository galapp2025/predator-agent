"""Tests for Features 5–6 (WhatsApp writer + turnout prediction)."""

from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.intelligence.prediction_engine import monte_carlo_turnout
from app.intelligence.whatsapp_writer import build_message_package
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.get("/health")
        yield ac


def _sample_voter(**overrides):
    base = {
        "id": "test-voter-1",
        "first_name": "דרור",
        "last_name": "כהן",
        "city": "פתח תקווה",
        "neighborhood": "נווה עוז",
        "phone": "0501234567",
        "support_score": 0.72,
        "turnout_history": 0.68,
        "gotv_category": "swing",
        "enriched_at": "2026-01-01T00:00:00Z",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_monte_carlo_empty_voters():
    out = monte_carlo_turnout([])
    assert out["predicted"] == 0.0
    assert out["ci_lower"] <= out["ci_upper"]


@pytest.mark.asyncio
async def test_monte_carlo_all_safe_high_turnout():
    voters = [
        {
            "id": str(i),
            "gotv_category": "safe",
            "turnout_history": 0.92,
            "support_score": 0.9,
        }
        for i in range(200)
    ]
    out = monte_carlo_turnout(voters, simulations=2000)
    assert out["predicted"] > 80
    assert out["ci_lower"] < out["predicted"] < out["ci_upper"]


@pytest.mark.asyncio
async def test_monte_carlo_all_at_risk_low_turnout():
    voters = [
        {
            "id": str(i),
            "gotv_category": "at_risk",
            "turnout_history": 0.12,
            "support_score": 0.4,
        }
        for i in range(200)
    ]
    out = monte_carlo_turnout(voters, simulations=2000)
    assert out["predicted"] < 40


def test_monte_carlo_performance():
    voters = [
        {
            "id": str(i),
            "gotv_category": "swing",
            "turnout_history": 0.55,
            "neighborhood": "מרכז",
        }
        for i in range(500)
    ]
    start = time.perf_counter()
    monte_carlo_turnout(voters, simulations=10_000)
    assert time.perf_counter() - start < 3.0


@pytest.mark.asyncio
async def test_whatsapp_package_three_variants():
    pkg = await build_message_package(_sample_voter(), campaign_topic="חינוך", persist=False)
    variants = pkg["message_variants"]
    assert len(variants) == 3
    texts = [variants[k]["text"] for k in variants]
    assert len(set(texts)) >= 2
    assert pkg["personalization_score"] >= 0.70
    assert all(variants[k]["character_count"] < 500 for k in variants)


@pytest.mark.asyncio
async def test_whatsapp_topic_changes_content():
    edu = await build_message_package(_sample_voter(), campaign_topic="חינוך", persist=False)
    sec = await build_message_package(_sample_voter(), campaign_topic="בטחון", persist=False)
    assert edu["message_variants"]["variant_a"]["text"] != sec["message_variants"]["variant_a"]["text"]


@pytest.mark.asyncio
async def test_whatsapp_no_osint_fallback():
    voter = _sample_voter(enriched_at=None, support_score=0.5, turnout_history=0.5)
    voter.pop("enriched_at", None)
    pkg = await build_message_package(voter, persist=False)
    assert pkg["osint_signals"]
    assert "נווה עוז" in pkg["message_variants"]["variant_a"]["text"] or "נווה עוז" in pkg["neighborhood"]


@pytest.mark.asyncio
async def test_api_whatsapp_generate_404(client):
    res = await client.post("/api/intel/whatsapp/generate", json={"voter_id": "NO-SUCH-ID"})
    assert res.status_code == 404
    assert res.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_api_predict_turnout(client):
    res = await client.post(
        "/api/intel/predict/turnout",
        json={"scope": "city", "confidence_level": 0.95},
    )
    assert res.status_code == 200
    data = res.json()
    t = data["turnout"]
    assert 0 <= t["predicted"] <= 100
    assert t["ci_lower"] <= t["ci_upper"]
    if t["predicted"] > 0:
        assert t["ci_lower"] < t["predicted"] < t["ci_upper"]
    assert len(data["sensitivity_analysis"]) >= 3


@pytest.mark.asyncio
async def test_api_predict_trend(client):
    res = await client.get("/api/intel/predict/trend?days=30")
    assert res.status_code == 200
    data = res.json()
    assert len(data["trend"]) == 31


@pytest.mark.asyncio
async def test_api_predict_what_if(client):
    res = await client.post(
        "/api/intel/predict/what-if",
        json={"scenario": "convert_swing", "target_count": 50, "target_neighborhood": ""},
    )
    if res.status_code == 404:
        pytest.skip("no voters in test db")
    assert res.status_code == 200
    data = res.json()
    assert data["scenario_turnout"] >= data["baseline_turnout"]


@pytest.mark.asyncio
async def test_api_predict_comparative(client):
    res = await client.get("/api/intel/predict/comparative?election_type=municipal")
    assert res.status_code == 200
    assert len(res.json()["elections"]) == 3
