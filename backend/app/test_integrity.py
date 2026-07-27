"""
BlackOpps — Integrity Self-Test Suite
Run: python3 backend/app/test_integrity.py
Exit code 0 = ALL PASS. Exit code 1 = FAILURES FOUND.
"""

from __future__ import annotations

import io
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://blackopps-api-production.up.railway.app"
FRONTEND = "https://blackopps.vercel.app"
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
    except Exception as e:
        return 0, str(e)


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
