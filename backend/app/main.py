"""BlackOpps FastAPI — routing only. Business logic lives in services/intelligence."""

from __future__ import annotations

import logging
import os
import traceback
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from fastapi import File, HTTPException, Query, Request, UploadFile
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from app import db, services
from app.intelligence.api_integration import get_pipeline
from app.intelligence.auth import AuthMiddleware, RateLimiter
from app.intelligence.prediction_engine import router as prediction_router
from app.intelligence.whatsapp_writer import router as whatsapp_router
from app.intelligence.influence import router as influence_router
from app.intelligence.messaging import router as messaging_router
from app.intelligence.sentiment_tracker import router as sentiment_router
from app.intelligence.war_room import router as war_room_router
from app.intelligence.dossier_manager import router as dossier_router
from app.intelligence.trend_intel import router as trend_router
from app.intelligence.psychological_profiler import router as psycho_router
from app.intelligence.message_writer import router as writer_router
from app.intelligence.voter_intel_deep import router as voter_intel_deep_router
from app.schemas import (
    AgentsResponse,
    AgentInfo,
    AnalyzeRequest,
    CompareRequest,
    DispatchRequest,
    DispatchResponse,
    DispatchStats,
    GotvRequest,
    HealthResponse,
    ImportResult,
    PredictRequest,
    VoterCreate,
    VoterListResponse,
    VoterOut,
    VoterUpdate,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("blackopps.api")

API_KEYS_ENV = os.getenv("BLACKOPPS_API_KEYS", "").strip()
auth = AuthMiddleware()
rate_limiter = RateLimiter(requests_per_minute=100, ip_requests_per_minute=30)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await db.init_db()
    get_pipeline(
        opensanctions_key=os.getenv("OPENSANCTIONS_API_KEY"),
        newsapi_key=os.getenv("NEWSAPI_KEY"),
    )
    if auth.is_configured:
        logger.info("Auth enabled (%s keys)", auth.key_count())
    else:
        logger.warning("Auth disabled — set BLACKOPPS_API_KEYS to enforce X-API-Key")
    logger.info(
        "BlackOpps API ready · db=%s · url=%s",
        db.DB_PATH,
        "sqlite" if db.IS_SQLITE else "postgres",
    )
    yield


app = FastAPI(
    title="BlackOpps Election Intelligence",
    version="5.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://blackopps.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(war_room_router, prefix="/api")
app.include_router(messaging_router, prefix="/api")
app.include_router(sentiment_router, prefix="/api")
app.include_router(influence_router, prefix="/api")
app.include_router(whatsapp_router, prefix="/api")
app.include_router(prediction_router, prefix="/api")
app.include_router(dossier_router, prefix="/api")
app.include_router(trend_router, prefix="/api")
app.include_router(psycho_router, prefix="/api")
app.include_router(writer_router, prefix="/api")
app.include_router(voter_intel_deep_router, prefix="/api")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if request.url.path != "/health":
        allowed = await rate_limiter.check(request)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded", "retry_after": 60},
                headers={"Retry-After": "60"},
            )
        if auth.is_configured:
            api_key = request.headers.get("X-API-Key")
            if not auth.validate(api_key):
                return JSONResponse(
                    status_code=401,
                    content={"error": "Unauthorized", "detail": "Missing or invalid X-API-Key"},
                )
    response = await call_next(request)
    return auth.inject_security_headers(response)


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if exc.status_code == 404:
        return JSONResponse(status_code=404, content={"error": "Not found", "detail": detail})
    if exc.status_code == 422:
        return JSONResponse(status_code=422, content={"error": "Validation error", "detail": detail})
    return JSONResponse(status_code=exc.status_code, content={"error": "Request error", "detail": detail})


@app.exception_handler(ValidationError)
async def validation_exception_handler(_request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": "Validation error", "detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error on %s %s\n%s", request.method, request.url.path, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"error": "Internal error", "detail": "An unexpected error occurred"},
    )


def _voter_out(row: dict[str, Any]) -> VoterOut:
    normalized = db.normalize_voter_row(row) or row
    return VoterOut.model_validate(normalized)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    try:
        return HealthResponse(
            status="ok",
            service="blackopps",
            version="5.0.0",
            auth_configured=auth.is_configured,
            modules=[
                "gotv",
                "scoring",
                "pipeline",
                "opposition",
                "pdf",
                "collectors",
                "messaging",
                "influence",
                "sentiment_tracker",
                "war_room",
                "whatsapp_writer",
                "prediction_engine",
                "psychological_profiler",
                "message_writer",
                "dossier_manager",
                "trend_intel",
                "voter_intel_deep",
            ],
        )
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.get("/agents", response_model=AgentsResponse)
async def list_agents() -> AgentsResponse:
    try:
        return AgentsResponse(
            agents=[AgentInfo(id="blackopps-intel", type="osint", status="active")],
            modules=[
                "gotv",
                "pipeline",
                "opposition",
                "pdf",
                "dispatch",
                "messaging",
                "influence",
                "sentiment_tracker",
                "war_room",
                "whatsapp_writer",
                "prediction_engine",
                "psychological_profiler",
                "message_writer",
                "dossier_manager",
                "trend_intel",
                "voter_intel_deep",
            ],
        )
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.get("/voters", response_model=VoterListResponse)
async def list_voters(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    category: str | None = None,
    search: str | None = None,
) -> VoterListResponse:
    try:
        rows, total = await db.list_voters(limit=limit, offset=offset, category=category, search=search)
        return VoterListResponse(
            voters=[_voter_out(r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.get("/voters/{voter_id}", response_model=VoterOut)
async def get_voter(voter_id: str) -> VoterOut:
    try:
        row = await db.get_voter(voter_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Voter '{voter_id}' not found")
        return _voter_out(row)
    except HTTPException:
        raise
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.post("/voters", response_model=VoterOut, status_code=201)
async def create_voter(payload: VoterCreate) -> VoterOut:
    try:
        row = await services.create_voter(payload)
        return _voter_out(row)
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.patch("/voters/{voter_id}", response_model=VoterOut)
async def update_voter(voter_id: str, payload: VoterUpdate) -> VoterOut:
    try:
        if not await db.get_voter(voter_id):
            raise HTTPException(status_code=404, detail=f"Voter '{voter_id}' not found")
        row = await db.update_voter(voter_id, payload.model_dump(exclude_unset=True))
        if not row:
            raise HTTPException(status_code=404, detail=f"Voter '{voter_id}' not found")
        return _voter_out(row)
    except HTTPException:
        raise
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.post("/voters/import", response_model=ImportResult)
async def import_voters(file: UploadFile = File(...)) -> ImportResult:
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=422, detail="Empty upload")
        result = await services.import_excel(BytesIO(content))
        return ImportResult.model_validate(result)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.post("/voters/{voter_id}/enrich")
async def enrich_voter(voter_id: str) -> dict[str, Any]:
    try:
        return await services.enrich_voter(voter_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.post("/analyze")
async def analyze(payload: AnalyzeRequest) -> dict[str, Any]:
    try:
        return await services.enrich_names(payload.names, payload.location, payload.jurisdiction)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.post("/analyze/voters")
async def analyze_voters(payload: AnalyzeRequest) -> dict[str, Any]:
    try:
        names = list(payload.names or [])
        for voter_id in payload.voter_ids or []:
            row = await db.get_voter(voter_id)
            if row:
                names.append(f"{row['first_name']} {row['last_name']}".strip())
        return await services.enrich_names(names, payload.location, payload.jurisdiction)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.post("/predict")
async def predict(payload: PredictRequest) -> dict[str, Any]:
    try:
        return await services.predict_voter(payload.name, payload.support_score, payload.turnout_history)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.post("/intel/gotv")
async def intel_gotv(payload: GotvRequest | None = None) -> dict[str, Any]:
    try:
        body = payload or GotvRequest()
        voters = [v.model_dump() for v in (body.voters or [])] or None
        return await services.classify_request_voters(voters=voters, names=body.names)
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.post("/intel/compare")
async def intel_compare(payload: CompareRequest) -> dict[str, Any]:
    try:
        name_a, name_b = payload.resolve_names()
        if not name_a or not name_b:
            raise HTTPException(status_code=422, detail="name_a and name_b are required")
        return await services.compare_candidates(name_a, name_b, payload.location, payload.jurisdiction)
    except HTTPException:
        raise
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.get("/intel/alerts")
async def intel_alerts(severity: str | None = None) -> dict[str, Any]:
    try:
        return services.alerts_payload(severity)
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.get("/intel/network/{name}")
async def intel_network(name: str, depth: int = Query(2, ge=1, le=5)) -> dict[str, Any]:
    try:
        return services.network_payload(name, depth)
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.get("/intel/timeline/{name}")
async def intel_timeline(name: str) -> dict[str, Any]:
    try:
        return services.timeline_payload(name)
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.get("/intel/briefing/{name}")
async def intel_briefing(name: str) -> dict[str, Any]:
    try:
        return await services.briefing_json(name)
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.get("/intel/briefing/{name}/pdf")
async def intel_briefing_pdf(name: str) -> StreamingResponse:
    try:
        pdf_bytes = await services.briefing_pdf_bytes(name)
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        safe = "".join(ch if ch.isascii() and (ch.isalnum() or ch in "-_") else "_" for ch in name).strip("_") or "subject"
        filename = f"briefing-{safe}-{stamp}.pdf"
        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(pdf_bytes)),
            },
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.get("/dispatch/queue/stats", response_model=DispatchStats)
async def dispatch_queue_stats() -> DispatchStats:
    try:
        return DispatchStats.model_validate(services.dispatch_stats())
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


@app.post("/dispatch", response_model=DispatchResponse)
async def dispatch_message(payload: DispatchRequest) -> DispatchResponse:
    try:
        record = services.enqueue_dispatch(
            voter_id=payload.voter_id,
            voter_name=payload.voter_name,
            channel=payload.channel,
            priority=payload.priority,
            message=payload.message,
            message_template=payload.message_template,
            custom_message=payload.custom_message,
        )
        return DispatchResponse(
            status=record["status"],
            message_id=record["message_id"],
            task_id=record["task_id"],
            channel=record["channel"],
            voter_id=record.get("voter_id"),
            voter_name=record.get("voter_name"),
            queued_at=record["queued_at"],
        )
    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An unexpected error occurred") from None


def _print_banner() -> None:
    routes = sorted({getattr(r, "path", "") for r in app.routes if getattr(r, "path", "")})
    print("\n=== BlackOpps FastAPI ===", flush=True)
    for path in routes:
        print(f"  {path}", flush=True)
    print("=========================\n", flush=True)


_print_banner()
