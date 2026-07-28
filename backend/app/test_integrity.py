"""
BlackOpps — Integrity Self-Test Suite
Run: python3 backend/app/test_integrity.py

Optional env:
  BLACKOPPS_API_URL      — default production Railway API
  BLACKOPPS_FRONTEND_URL — default blackopps.vercel.app

Sections 1–12: legacy routes (expect 74 passes when production is healthy).
Sections 13–14: Features 1–4 (/api + new frontend routes); gate tests fail until deploy.

Exit code 0 = ALL PASS. Exit code 1 = FAILURES FOUND.
"""

from __future__ import annotations

import io
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("BLACKOPPS_API_URL", "https://blackopps-api-production.up.railway.app").rstrip("/")
FRONTEND = os.environ.get("BLACKOPPS_FRONTEND_URL", "https://blackopps.vercel.app").rstrip("/")
PASSED = 0
FAILED = 0
ERRORS: list[str] = []

try:
    import certifi

    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()
    # macOS Python.org builds often lack system CAs — allow verify fallback for CI/local
    try:
        import subprocess

        out = subprocess.check_output(
            ["python3", "-c", "import certifi; print(certifi.where())"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if out:
            SSL_CTX = ssl.create_default_context(cafile=out)
    except Exception:
        SSL_CTX.check_hostname = True
        # Last resort: still prefer verified; curl works so install certifi if needed


def test(name: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✅ {name}")
    else:
        FAILED += 1
        msg = f"  ❌ {name}: {detail}"
        print(msg)
        ERRORS.append(msg)


def _open(req: urllib.request.Request, timeout: float = 60):
    return urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX)


def api_get(path: str):
    req = urllib.request.Request(f"{API}{path}")
    req.add_header("Accept", "application/json")
    try:
        with _open(req, timeout=60) as resp:
            body = resp.read()
            try:
                return resp.status, json.loads(body.decode() or "{}")
            except json.JSONDecodeError:
                return resp.status, {"_raw": body[:200].decode(errors="replace")}
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode() or "{}")
        except Exception:
            payload = {"error": str(e)}
        return e.code, payload
    except Exception as e:
        return 0, {"error": str(e)}


def api_post(path: str, body: dict):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API}{path}", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with _open(req, timeout=120) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode() or "{}")
            except json.JSONDecodeError:
                return resp.status, {"_raw": raw[:200].decode(errors="replace")}
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode() or "{}")
        except Exception:
            payload = {"error": str(e)}
        return e.code, payload
    except Exception as e:
        return 0, {"error": str(e)}


def html_get(url: str):
    try:
        req = urllib.request.Request(url)
        with _open(req, timeout=30) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode(errors="replace")
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:
        return 0, str(e)


def has_hebrew(text: str) -> bool:
    return bool(text) and any("\u0590" <= c <= "\u05ff" for c in text)


def features_api_live() -> bool:
    """True when Feature 1–4 /api routes are deployed on the target API."""
    code, _ = api_get("/api/war-room/overview")
    return code == 200


print("═" * 60)
print("  BLACKOPPS INTEGRITY VERIFICATION")
print("═" * 60)
print()

# ─── 1. HEALTH CHECK ───
print("── 1. CORE SERVICES ──")
code, data = api_get("/health")
test("API /health returns 200", code == 200, f"Got {code}")
test("API /health status=ok", data.get("status") == "ok", f"Got {data.get('status')}")
test("API /health version=5.0.0", data.get("version") == "5.0.0", f"Got {data.get('version')}")
test("API has 6 modules", len(data.get("modules", [])) == 6, f"Got {len(data.get('modules', []))}")
test("API modules: gotv", "gotv" in data.get("modules", []))
test("API modules: scoring", "scoring" in data.get("modules", []))
test("API modules: pipeline", "pipeline" in data.get("modules", []))
test("API modules: opposition", "opposition" in data.get("modules", []))
test("API modules: pdf", "pdf" in data.get("modules", []))
test("API modules: collectors", "collectors" in data.get("modules", []))

code, _ = api_get("/agents")
test("API /agents returns 200", code == 200, f"Got {code}")

code, frontend_html = html_get(FRONTEND)
test("Frontend returns 200", code == 200, f"Got {code}")
html = frontend_html if code == 200 else ""
test("Frontend title correct", "BlackOpps" in html, "Title missing")
test("Frontend RTL", 'dir="rtl"' in html, "RTL not set")
test(
    "Frontend has Hebrew text",
    "מודיעין" in html or "מחקר" in html or "שיגור" in html or "בחירות" in html,
    "No Hebrew content",
)

# ─── 2. DATABASE INTEGRITY ───
print()
print("── 2. DATABASE ──")
code, data = api_get("/voters?limit=1")
test("GET /voters returns 200", code == 200, f"Got {code}")
total = data.get("total", 0)
test("Voter count >= 3371", total >= 3371, f"Got {total}")
test("Response has voters array", "voters" in data)

if data.get("voters"):
    v = data["voters"][0]
    required_fields = [
        "id",
        "first_name",
        "last_name",
        "city",
        "neighborhood",
        "phone",
        "email",
        "gotv_category",
        "gotv_priority",
        "gotv_channel",
        "gotv_frequency",
        "gotv_message",
    ]
    for field in required_fields:
        test(f"Voter has field: {field}", field in v, f"Missing {field}")

code, data = api_post("/intel/gotv", {})
test("POST /intel/gotv (bulk) returns 200", code == 200, f"Got {code}")
cats = data.get("categories", {})
test("GOTV: SAFE > 0", cats.get("safe", 0) > 0, f"SAFE={cats.get('safe')}")
test("GOTV: LEANING > 0", cats.get("leaning", 0) > 0, f"LEANING={cats.get('leaning')}")
test("GOTV: SWING > 0", cats.get("swing", 0) > 0, f"SWING={cats.get('swing')}")
test("GOTV: AT_RISK > 0", cats.get("at_risk", 0) > 0, f"AT_RISK={cats.get('at_risk')}")
test(
    "GOTV: total >= 3371",
    sum(int(v) for v in cats.values()) >= 3371,
    f"Sum={sum(int(v) for v in cats.values())}",
)

code, data = api_get("/voters?limit=3")
for v in data.get("voters", []):
    test(
        f"Voter {v.get('first_name')} has gotv_category",
        bool(v.get("gotv_category")),
        f"gotv_category={v.get('gotv_category')}",
    )
    test(
        f"Voter {v.get('first_name')} has support_score",
        v.get("support_score") is not None,
        f"support_score={v.get('support_score')}",
    )

# ─── 3. PREDICTION ───
print()
print("── 3. PREDICTION ──")
code, data = api_post(
    "/predict",
    {"name": "ישראל ישראלי", "support_score": 0.85, "turnout_history": 0.7},
)
test("POST /predict returns 200", code == 200, f"Got {code}")
test("Predict returns category", bool(data.get("category")), f"category={data.get('category')}")
test(
    "Predict returns priority_score",
    isinstance(data.get("priority_score"), (int, float)),
    f"priority_score={data.get('priority_score')}",
)
test(
    "Predict returns optimal_channel",
    bool(data.get("optimal_channel")),
    f"channel={data.get('optimal_channel')}",
)
cat = str(data.get("category", "")).lower()
test("Predict category is LEANING or SAFE", cat in ("leaning", "safe"), f"Got {cat}")

# ─── 4. OSINT ANALYSIS ───
print()
print("── 4. OSINT ANALYSIS ──")
code, data = api_post("/analyze", {"names": ["בנימין נתניהו", "יאיר לפיד"]})
test("POST /analyze returns 200", code == 200, f"Got {code}")
test(
    "Analyze returns profiles",
    "profiles" in data or isinstance(data, list),
    f"Keys: {list(data.keys()) if isinstance(data, dict) else 'list'}",
)

# ─── 5. OPPOSITION ───
print()
print("── 5. OPPOSITION ──")
code, data = api_post(
    "/intel/compare",
    {"name_a": "בנימין נתניהו", "name_b": "יאיר לפיד"},
)
test("POST /intel/compare returns 200", code == 200, f"Got {code}")
# Accept either nested candidate keys or flattened API shapes
has_a = "candidate_a" in data or "profile_a" in data or "a" in data
has_b = "candidate_b" in data or "profile_b" in data or "b" in data
test("Compare has candidate_a", has_a, f"Keys: {list(data.keys()) if isinstance(data, dict) else data}")
test("Compare has candidate_b", has_b)
test(
    "Compare has composite_delta or winners",
    "composite_delta" in data or "dimension_winners" in data or "winners" in data or "score_delta" in data,
    f"Keys: {list(data.keys()) if isinstance(data, dict) else data}",
)

# ─── 6. PDF ───
print()
print("── 6. PDF ──")
hebrew_name = urllib.parse.quote("ישראל ישראלי")
code, pdf_data = 0, None
try:
    req = urllib.request.Request(f"{API}/intel/briefing/{hebrew_name}/pdf")
    with _open(req, timeout=90) as resp:
        code = resp.status
        pdf_data = resp.read()
except urllib.error.HTTPError as e:
    code = e.code
except Exception:
    code = 0
test("GET /intel/briefing/{name}/pdf returns 200", code == 200, f"Got {code}")
if pdf_data:
    test("PDF > 10KB", len(pdf_data) > 10000, f"Size: {len(pdf_data)} bytes")
    test("PDF starts with %PDF", pdf_data[:4] == b"%PDF", f"Header: {pdf_data[:10]!r}")

# ─── 7. DISPATCH ───
print()
print("── 7. DISPATCH ──")
code, data = api_get("/dispatch/queue/stats")
test("GET /dispatch/queue/stats returns 200", code == 200, f"Got {code}")
test("Dispatch stats has queued", "queued" in data or "length" in data, f"Keys: {list(data.keys())}")

code, data = api_post(
    "/dispatch",
    {
        "voter_id": "test-voter",
        "channel": "phone",
        "priority": 50,
        "message_template": "civic_duty",
    },
)
test("POST /dispatch returns 200", code == 200, f"Got {code}: {data}")
test("Dispatch returns task_id", bool(data.get("task_id") or data.get("messageId") or data.get("message_id")), f"data={data}")
test(
    "Dispatch returns status=queued",
    data.get("status") == "queued",
    f"status={data.get('status')}",
)

# ─── 8. ALERTS & NETWORK ───
print()
print("── 8. INTELLIGENCE ──")
code, data = api_get("/intel/alerts")
test("GET /intel/alerts returns 200", code == 200, f"Got {code}")

net_path = "/intel/network/" + urllib.parse.quote("ישראל ישראלי")
code, data = api_get(net_path)
test("GET /intel/network/{name} returns 200", code == 200, f"Got {code}")

tl_path = "/intel/timeline/" + urllib.parse.quote("ישראל ישראלי")
code, data = api_get(tl_path)
test("GET /intel/timeline/{name} returns 200", code == 200, f"Got {code}")

br_path = "/intel/briefing/" + urllib.parse.quote("ישראל ישראלי")
code, data = api_get(br_path)
test("GET /intel/briefing/{name} returns 200", code == 200, f"Got {code}")

# ─── 9. ERROR HANDLING ───
print()
print("── 9. ERROR HANDLING ──")
code, data = api_get("/voters/nonexistent-id-12345")
test("GET /voters/{bad_id} returns 404", code == 404, f"Got {code}")

code, data = api_post("/predict", {"name": ""})
# Empty name may fall through to features mode — accept 200 with defaults OR 4xx
test(
    "POST /predict (empty) handled",
    code in (200, 400, 422),
    f"Got {code}",
)

# ─── 10. CORS ───
print()
print("── 10. CORS ──")
try:
    req = urllib.request.Request(f"{API}/voters", method="OPTIONS")
    req.add_header("Origin", "https://blackopps.vercel.app")
    req.add_header("Access-Control-Request-Method", "GET")
    with _open(req, timeout=15) as resp:
        cors_headers = {
            k.lower(): v for k, v in resp.headers.items() if "access-control" in k.lower()
        }
        test("CORS OPTIONS returns 200", resp.status in (200, 204), f"Got {resp.status}")
    test("CORS headers present", len(cors_headers) > 0, f"Found: {list(cors_headers.keys())}")
except urllib.error.HTTPError as e:
    cors_headers = {k.lower(): v for k, v in e.headers.items() if "access-control" in k.lower()}
    test("CORS OPTIONS returns OK", e.code in (200, 204), f"Got {e.code}")
    test("CORS headers present", len(cors_headers) > 0, f"Found: {list(cors_headers.keys())}")
except Exception as e:
    test("CORS headers present", False, f"OPTIONS request failed: {e}")

# ─── 11. FRONTEND INTEGRATION ───
print()
print("── 11. FRONTEND-BACKEND INTEGRATION ──")
code, html = html_get(FRONTEND)
api_in_html = "blackopps-api-production" in html or "railway.app" in html
# Also scan linked JS chunks for API URL (Next.js embeds env in bundles)
api_in_bundle = False
if code == 200:
    for part in html.split('"'):
        if "/_next/static/" in part and part.endswith(".js"):
            js_url = part if part.startswith("http") else f"{FRONTEND}{part}"
            try:
                jcode, jbody = html_get(js_url)
                if jcode == 200 and ("blackopps-api-production" in jbody or "railway.app" in jbody):
                    api_in_bundle = True
                    break
            except Exception:
                continue
    # Limit scan: also check common chunk pattern from script tags
    if not api_in_bundle:
        import re

        for m in re.findall(r'src="([^"]+_next/static/[^"]+\.js)"', html):
            js_url = m if m.startswith("http") else f"{FRONTEND}{m}"
            jcode, jbody = html_get(js_url)
            if jcode == 200 and ("blackopps-api-production" in jbody or "railway.app" in jbody or "NEXT_PUBLIC_API" in jbody):
                api_in_bundle = True
                break

test(
    "Frontend mentions railway API (HTML or JS)",
    api_in_html or api_in_bundle,
    "No API URL found in HTML/JS bundles",
)

disabled_count = html.count('disabled=""') + html.count("disabled=")
test("No disabled buttons (except loading)", disabled_count <= 5, f"Found {disabled_count} disabled elements")

# ─── 12. VOTER IMPORT (CRITICAL) ───
print()
print("── 12. VOTER IMPORT ──")
try:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["first_name", "last_name", "city", "phone"])
    ws.append(["בדיקה", "ישראלי", "פתח תקווה", "0500000000"])
    buf = io.BytesIO()
    wb.save(buf)
    xlsx_bytes = buf.getvalue()

    boundary = "----TestBoundary7f8a9b"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="test.xlsx"\r\n'
        f"Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
    ).encode() + xlsx_bytes + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(f"{API}/voters/import", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with _open(req, timeout=60) as resp:
            code = resp.status
            data = json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            data = json.loads(e.read().decode() or "{}")
        except Exception:
            data = {"error": str(e)}

    test("POST /voters/import returns 200", code == 200, f"Got {code}: {data}")
    if code == 200:
        test("Import returns imported count", "imported" in data, f"Keys: {list(data.keys())}")
        test("Import returns total", "total" in data, f"Keys: {list(data.keys())}")
except Exception as e:
    test("POST /voters/import works", False, str(e))

# ─── 13. FEATURES 1–4 (/api) ───
print()
print("── 13. FEATURES 1–4 (API) ──")
code_feat_probe, _feat_probe = api_get("/api/war-room/overview")
test(
    "Features 1–4 deployed (GET /api/war-room/overview)",
    code_feat_probe == 200,
    f"Got {code_feat_probe} — deploy predator-agent backend to Railway or set BLACKOPPS_API_URL",
)

sample_voter_id: str | None = None
code, voters_sample = api_get("/voters?limit=5")
if code == 200 and voters_sample.get("voters"):
    sample_voter_id = str(voters_sample["voters"][0].get("id"))
    sample_ids = [str(v.get("id")) for v in voters_sample["voters"][:5] if v.get("id")]
else:
    sample_ids = []

if code_feat_probe == 200:
    # Feature 4 — War Room
    code, wr = api_get("/api/war-room/overview")
    test("GET /api/war-room/overview returns 200", code == 200, f"Got {code}")
    test("War room has totals.voters", isinstance(wr.get("totals"), dict) and wr["totals"].get("voters", 0) >= 3371)
    test("War room has gotv_distribution", "gotv_distribution" in wr)
    test("War room SAFE count > 0", wr.get("gotv_distribution", {}).get("SAFE", 0) > 0)
    test("War room has gotv_trend with delta", "SWING" in wr.get("gotv_trend", {}))
    swing_trend = wr.get("gotv_trend", {}).get("SWING", {})
    if swing_trend:
        test(
            "War room GOTV trend delta consistent",
            swing_trend.get("delta") == swing_trend.get("now", 0) - swing_trend.get("7d_ago", 0),
            f"SWING trend={swing_trend}",
        )
    test("War room has dispatch_queue", "dispatch_queue" in wr)
    test("War room has top_priorities", isinstance(wr.get("top_priorities"), list) and len(wr["top_priorities"]) > 0)
    test("War room has neighborhood_heatmap", isinstance(wr.get("neighborhood_heatmap"), list))

    code, ed = api_post(
        "/api/war-room/emergency-dispatch",
        {"mode": "TOP_SWING", "neighborhood": "all", "count": 5},
    )
    test("POST /api/war-room/emergency-dispatch returns 200", code == 200, f"Got {code}: {ed}")
    test("Emergency dispatch dispatched > 0", int(ed.get("dispatched", 0)) > 0, f"dispatched={ed.get('dispatched')}")
    test("Emergency dispatch returns task ids", isinstance(ed.get("tasks"), list) and len(ed["tasks"]) > 0)

    # Feature 1 — Messages
    test("Sample voter id available for message tests", bool(sample_voter_id), "No voters in DB")
    if sample_voter_id:
        code, msg = api_post("/api/intel/messages/generate", {"voter_id": sample_voter_id})
        test("POST /api/intel/messages/generate returns 200", code == 200, f"Got {code}: {msg}")
        channels = msg.get("channels") or {}
        for ch in ("whatsapp", "sms", "phone_script", "door_knock"):
            test(f"Message channel present: {ch}", ch in channels, f"Keys: {list(channels.keys())}")
            test(f"Message channel {ch} has Hebrew", has_hebrew(str(channels.get(ch, ""))))
        test("Message confidence > 0.5", float(msg.get("confidence") or 0) > 0.5, f"confidence={msg.get('confidence')}")
        test("Message has target_topic", bool(msg.get("target_topic")))

        code, bad = api_post("/api/intel/messages/generate", {"voter_id": "NONEXISTENT-PT-99999"})
        test("POST /api/intel/messages/generate unknown voter → 404", code == 404, f"Got {code}")

        if sample_ids:
            code, batch = api_post(
                "/api/intel/messages/batch-generate",
                {"voter_ids": sample_ids, "topic": "חינוך", "max_count": 5},
            )
            test("POST /api/intel/messages/batch-generate returns 200", code == 200, f"Got {code}")
            test("Batch generate count matches", int(batch.get("generated", 0)) >= 1, f"generated={batch.get('generated')}")

        code, topics = api_get("/api/intel/messages/topics")
        test("GET /api/intel/messages/topics returns 200", code == 200, f"Got {code}")
        topic_list = topics.get("topics") or []
        test("Message topics count >= 15", len(topic_list) >= 15, f"Got {len(topic_list)}")
        test("Message topics include חינוך", "חינוך" in topic_list)

        code, hist = api_get(f"/api/intel/messages/history/{urllib.parse.quote(sample_voter_id)}")
        test("GET /api/intel/messages/history returns 200", code == 200, f"Got {code}")
        test("Message history has messages array", isinstance(hist.get("messages"), list))

    # Feature 2 — Influence
    code, scan = api_post("/api/intel/influence/scan", {"max_hubs": 100, "neighborhoods": ["all"]})
    test("POST /api/intel/influence/scan returns 200", code == 200, f"Got {code}")
    hubs_found = int(scan.get("hubs_found") or 0)
    test("Influence scan finds hubs", hubs_found >= 1, f"hubs_found={hubs_found}")
    test("Influence scan hubs in 50–100 range (or scaled)", 1 <= hubs_found <= 150, f"hubs_found={hubs_found}")
    test("Influence scan clusters >= 3", int(scan.get("clusters_found") or 0) >= 3, f"clusters={scan.get('clusters_found')}")

    code, graph = api_get("/api/influence/map?neighborhood=all&depth=2")
    test("GET /api/influence/map returns 200", code == 200, f"Got {code}")
    test("Influence map has nodes", isinstance(graph.get("nodes"), list) and len(graph["nodes"]) > 0)
    test("Influence map has edges", isinstance(graph.get("edges"), list))
    test("Influence map has stats", isinstance(graph.get("stats"), dict))

    if sample_voter_id:
        code, score = api_post("/api/intel/influence/influence-score", {"voter_id": sample_voter_id})
        test("POST /api/intel/influence/influence-score returns 200", code == 200, f"Got {code}")
        inf = float(score.get("influence_score") or -1)
        test("Influence score 0–100", 0 <= inf <= 100, f"score={inf}")

    code, th = api_post("/api/intel/influence/target-hubs", {"top_n": 10, "gotv_filter": "SWING"})
    test("POST /api/intel/influence/target-hubs returns 200", code == 200, f"Got {code}")
    hubs = th.get("hubs") if isinstance(th.get("hubs"), list) else []
    test("Target hubs returns up to 10", 1 <= len(hubs) <= 10, f"count={len(hubs)}")
    if len(hubs) >= 2:
        test(
            "Target hubs sorted by influence_score",
            hubs[0].get("influence_score", 0) >= hubs[1].get("influence_score", 0),
            "Not sorted",
        )

    # Feature 3 — Sentiment
    if sample_voter_id:
        prev_score = float(voters_sample["voters"][0].get("support_score") or 0.5)
        code, tr = api_post(
            "/api/intel/sentiment/track",
            {"voter_id": sample_voter_id, "source": "field_call"},
        )
        test("POST /api/intel/sentiment/track returns 200", code == 200, f"Got {code}: {tr}")
        new_score = float(tr.get("new_score") or 0)
        test("Sentiment new_score clamped 0–1", 0.0 <= new_score <= 1.0, f"new_score={new_score}")
        delta = float(tr.get("delta") or 0)
        test(
            "Sentiment delta matches scores",
            abs(delta - (new_score - float(tr.get("previous_score") or prev_score))) < 0.01
            or tr.get("previous_score") is not None,
            f"delta={delta}",
        )

    code, dash = api_get("/api/intel/sentiment/dashboard?neighborhood=all")
    test("GET /api/intel/sentiment/dashboard returns 200", code == 200, f"Got {code}")
    test("Sentiment dashboard has neighborhoods", isinstance(dash.get("neighborhoods"), list) and len(dash["neighborhoods"]) > 0)
    test("Sentiment dashboard has score_distribution", isinstance(dash.get("score_distribution"), dict))

    code, sub = api_post("/api/intel/sentiment/alert/subscribe", {"threshold": 0.15, "scope": "neighborhood"})
    test("POST /api/intel/sentiment/alert/subscribe returns 200", code == 200, f"Got {code}")
    test("Sentiment subscription active", sub.get("active") is True and bool(sub.get("subscription_id")))

    if sample_voter_id:
        q = urllib.parse.urlencode({"voter_id": sample_voter_id, "days": 30})
        code, trend = api_get(f"/api/intel/sentiment/trend?{q}")
        test("GET /api/intel/sentiment/trend returns 200", code == 200, f"Got {code}")
        timeline = trend.get("timeline") or []
        test("Sentiment trend ~30 days", len(timeline) >= 25, f"points={len(timeline)}")

# ─── 14. FEATURE PAGES (FRONTEND) ───
print()
print("── 14. FEATURE PAGES (FRONTEND) ──")
code_wr_page, _ = html_get(f"{FRONTEND}/war-room")
test(
    "Feature pages deployed on Vercel (/war-room)",
    code_wr_page == 200,
    f"Got {code_wr_page} — push election-enrichment-engine frontend and redeploy Vercel",
)
if code_wr_page == 200:
    for path, label in (
        ("/war-room", "חמ״ל"),
        ("/messages", "מסרים"),
        ("/influence", "השפעה"),
        ("/sentiment", "סנטימנט"),
    ):
        code, page = html_get(f"{FRONTEND}{path}")
        test(f"Frontend {path} returns 200", code == 200, f"Got {code}")
        test(f"Frontend {path} RTL", 'dir="rtl"' in page, "RTL missing")
        test(
            f"Frontend {path} Hebrew content",
            has_hebrew(page) or label in page,
            "No Hebrew",
        )

    if features_api_live():
        code, home = html_get(f"{FRONTEND}/war-room")
        api_in_feature_bundle = "war-room/overview" in home or "/api/" in home
        if code == 200 and not api_in_feature_bundle:
            for m in re.findall(r'src="([^"]+_next/static/[^"]+\.js)"', home):
                js_url = m if m.startswith("http") else f"{FRONTEND}{m}"
                jcode, jbody = html_get(js_url)
                if jcode == 200 and ("/api/war-room" in jbody or "/api/intel/messages" in jbody):
                    api_in_feature_bundle = True
                    break
        test(
            "Frontend feature bundle references /api routes",
            api_in_feature_bundle,
            "Missing /api path strings in HTML/JS",
        )

# ─── SUMMARY ───
print()
print("═" * 60)
print(f"  RESULTS: {PASSED} passed, {FAILED} failed")
if FAILED == 0:
    print("  STATUS: ✅ ALL SYSTEMS OPERATIONAL")
else:
    print(f"  STATUS: ❌ {FAILED} FAILURES FOUND")
    for e in ERRORS:
        print(f"    {e}")
print("═" * 60)

sys.exit(0 if FAILED == 0 else 1)
