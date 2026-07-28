"""BlackOpps voter persistence — SQLite by default, Postgres via DATABASE_URL."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# Repo root: predator-agent/  (…/backend/app/db.py → parents[2])
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
_DEFAULT_SQLITE = f"sqlite+aiosqlite:///{(DATA_DIR / 'blackopps.db').as_posix()}"


def _normalize_database_url(raw: str | None) -> str:
    """Accept Railway postgres:// URLs, plain paths, and SQLAlchemy URLs."""
    url = (raw or "").strip()
    if not url:
        return _DEFAULT_SQLITE
    if "://" not in url:
        path = Path(url).expanduser().resolve()
        return f"sqlite+aiosqlite:///{path.as_posix()}"
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("sqlite:///") and "+aiosqlite" not in url:
        return "sqlite+aiosqlite:///" + url[len("sqlite:///") :]
    return url


# Prefer DATABASE_URL; fall back to BLACKOPPS_DB path, then local SQLite file.
DATABASE_URL = _normalize_database_url(
    os.getenv("DATABASE_URL")
    or (os.getenv("BLACKOPPS_DB") and str(Path(os.getenv("BLACKOPPS_DB", "")).expanduser()))
    or _DEFAULT_SQLITE
)

IS_SQLITE = DATABASE_URL.startswith("sqlite")
if IS_SQLITE:
    DB_PATH = Path(urlparse(DATABASE_URL).path)
else:
    # Host/db fragment for logs (no credentials)
    DB_PATH = Path(DATABASE_URL.split("@")[-1].split("?")[0])

metadata = MetaData()

whatsapp_messages = Table(
    "whatsapp_messages",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("voter_id", String(64), nullable=False),
    Column("variant", String(32), nullable=False),
    Column("message_text", Text, nullable=False),
    Column("style", String(64), default=""),
    Column("personalization_score", Float, default=0.0),
    Column("created_at", Text, nullable=True),
    Column("scheduled_at", Text, nullable=True),
    Column("sent_at", Text, nullable=True),
    Column("campaign_topic", Text, default=""),
)

turnout_predictions = Table(
    "turnout_predictions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("scope", String(64), default=""),
    Column("predicted_turnout", Float, default=0.0),
    Column("ci_lower", Float, default=0.0),
    Column("ci_upper", Float, default=0.0),
    Column("simulations", Integer, default=10000),
    Column("generated_at", Text, nullable=True),
    Column("parameters", Text, default=""),
    Column("result_json", Text, default=""),
)

voters = Table(
    "voters",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("first_name", String(255), nullable=False),
    Column("last_name", String(255), nullable=False),
    Column("city", String(255), default=""),
    Column("neighborhood", String(255), default=""),
    Column("phone", String(64), default=""),
    Column("email", String(255), default=""),
    Column("support_score", Float, default=0.5),
    Column("turnout_history", Float, default=0.0),
    Column("gotv_category", String(32), default=""),
    Column("gotv_priority", Integer, default=0),
    Column("gotv_channel", String(64), default=""),
    Column("gotv_frequency", String(64), default=""),
    Column("gotv_message", Text, default=""),
    Column("enriched_at", Text, nullable=True),
    Column("created_at", Text, nullable=True),
    Column("updated_at", Text, nullable=True),
)

sentiment_history = Table(
    "sentiment_history",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("voter_id", String(64), nullable=False),
    Column("score", Float, nullable=False),
    Column("source", String(64), default=""),
    Column("delta", Float, default=0.0),
    Column("neighborhood", String(255), default=""),
    Column("timestamp", Text, nullable=False),
)

generated_messages = Table(
    "generated_messages",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("voter_id", String(64), nullable=False),
    Column("channel", String(32), nullable=False),
    Column("text", Text, nullable=False),
    Column("target_topic", String(64), default=""),
    Column("confidence", Float, default=0.0),
    Column("timestamp", Text, nullable=False),
)

sentiment_subscriptions = Table(
    "sentiment_subscriptions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("webhook_url", Text, default=""),
    Column("threshold", Float, default=0.15),
    Column("scope", String(32), default="neighborhood"),
    Column("active", Integer, default=1),
    Column("created_at", Text, nullable=True),
)

gotv_daily_snapshots = Table(
    "gotv_daily_snapshots",
    metadata,
    Column("snapshot_date", String(10), primary_key=True),
    Column("safe", Integer, default=0),
    Column("leaning", Integer, default=0),
    Column("swing", Integer, default=0),
    Column("at_risk", Integer, default=0),
    Column("lost", Integer, default=0),
    Column("created_at", Text, nullable=True),
)

VOTER_COLUMNS = (
    "id",
    "first_name",
    "last_name",
    "city",
    "neighborhood",
    "phone",
    "email",
    "support_score",
    "turnout_history",
    "gotv_category",
    "gotv_priority",
    "gotv_channel",
    "gotv_frequency",
    "gotv_message",
    "enriched_at",
    "created_at",
    "updated_at",
)

_engine: AsyncEngine | None = None
_Session: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    global _engine, _Session
    if _engine is None:
        kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if IS_SQLITE:
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_async_engine(DATABASE_URL, **kwargs)
        _Session = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def _session_factory() -> async_sessionmaker[AsyncSession]:
    if _Session is None:
        _get_engine()
    assert _Session is not None
    return _Session


async def init_db() -> None:
    if IS_SQLITE:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_voters_name ON voters (first_name, last_name)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_voters_category ON voters (gotv_category)"))
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_sentiment_voter ON sentiment_history (voter_id)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_messages_voter ON generated_messages (voter_id)")
        )


async def resolve_voter(voter_id: str) -> dict[str, Any] | None:
    row = await get_voter(voter_id)
    if row:
        return row
    async with _session_factory()() as db:
        stmt = select(voters).where(voters.c.id.like(f"%{voter_id[-8:]}%")).limit(1)
        found = (await db.execute(stmt)).mappings().first()
        return dict(found) if found else None


async def insert_sentiment_event(
    *,
    event_id: str,
    voter_id: str,
    score: float,
    source: str,
    delta: float,
    neighborhood: str,
    timestamp: str,
) -> None:
    async with _session_factory()() as db:
        await db.execute(
            sentiment_history.insert().values(
                id=event_id,
                voter_id=voter_id,
                score=score,
                source=source,
                delta=delta,
                neighborhood=neighborhood,
                timestamp=timestamp,
            )
        )
        await db.commit()


async def list_sentiment_history(voter_id: str, limit: int = 100) -> list[dict[str, Any]]:
    async with _session_factory()() as db:
        stmt = (
            select(sentiment_history)
            .where(sentiment_history.c.voter_id == voter_id)
            .order_by(sentiment_history.c.timestamp.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]


async def insert_generated_message(
    *,
    message_id: str,
    voter_id: str,
    channel: str,
    text: str,
    target_topic: str,
    confidence: float,
    timestamp: str,
) -> None:
    async with _session_factory()() as db:
        await db.execute(
            generated_messages.insert().values(
                id=message_id,
                voter_id=voter_id,
                channel=channel,
                text=text,
                target_topic=target_topic,
                confidence=confidence,
                timestamp=timestamp,
            )
        )
        await db.commit()


async def list_generated_messages(voter_id: str, limit: int = 50) -> list[dict[str, Any]]:
    async with _session_factory()() as db:
        stmt = (
            select(generated_messages)
            .where(generated_messages.c.voter_id == voter_id)
            .order_by(generated_messages.c.timestamp.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]


async def insert_sentiment_subscription(
    *,
    subscription_id: str,
    webhook_url: str,
    threshold: float,
    scope: str,
) -> None:
    async with _session_factory()() as db:
        await db.execute(
            sentiment_subscriptions.insert().values(
                id=subscription_id,
                webhook_url=webhook_url,
                threshold=threshold,
                scope=scope,
                active=1,
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        await db.commit()


async def upsert_gotv_snapshot(counts: dict[str, int]) -> None:
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    now = datetime.now(UTC).isoformat()
    async with _session_factory()() as db:
        await db.execute(
            text(
                """
                INSERT INTO gotv_daily_snapshots (snapshot_date, safe, leaning, swing, at_risk, lost, created_at)
                VALUES (:d, :safe, :leaning, :swing, :at_risk, :lost, :ts)
                ON CONFLICT(snapshot_date) DO UPDATE SET
                  safe=excluded.safe, leaning=excluded.leaning, swing=excluded.swing,
                  at_risk=excluded.at_risk, lost=excluded.lost, created_at=excluded.created_at
                """
            ),
            {
                "d": day,
                "safe": counts.get("safe", 0),
                "leaning": counts.get("leaning", 0),
                "swing": counts.get("swing", 0),
                "at_risk": counts.get("at_risk", 0),
                "lost": counts.get("lost", 0),
                "ts": now,
            },
        )
        await db.commit()


async def gotv_snapshot_on_date(date_str: str) -> dict[str, Any] | None:
    async with _session_factory()() as db:
        row = (
            await db.execute(
                select(gotv_daily_snapshots).where(gotv_daily_snapshots.c.snapshot_date == date_str)
            )
        ).mappings().first()
        return dict(row) if row else None


async def list_voters(
    *,
    limit: int = 100,
    offset: int = 0,
    category: str | None = None,
    search: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    async with _session_factory()() as db:
        filters = []
        if category:
            filters.append(func.lower(voters.c.gotv_category) == category.lower())
        if search:
            like = f"%{search}%"
            filters.append(
                (voters.c.first_name.like(like))
                | (voters.c.last_name.like(like))
                | (voters.c.city.like(like))
                | (voters.c.phone.like(like))
            )
        count_stmt = select(func.count()).select_from(voters)
        list_stmt = (
            select(voters)
            .order_by(voters.c.gotv_priority.desc(), voters.c.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        for f in filters:
            count_stmt = count_stmt.where(f)
            list_stmt = list_stmt.where(f)
        total = int((await db.execute(count_stmt)).scalar_one())
        rows = (await db.execute(list_stmt)).mappings().all()
        return [dict(r) for r in rows], total


async def get_voter(voter_id: str) -> dict[str, Any] | None:
    async with _session_factory()() as db:
        row = (await db.execute(select(voters).where(voters.c.id == voter_id))).mappings().first()
        return dict(row) if row else None


async def find_by_name(first_name: str, last_name: str) -> dict[str, Any] | None:
    async with _session_factory()() as db:
        row = (
            await db.execute(
                select(voters)
                .where(
                    func.lower(voters.c.first_name) == first_name.strip().lower(),
                    func.lower(voters.c.last_name) == last_name.strip().lower(),
                )
                .limit(1)
            )
        ).mappings().first()
        return dict(row) if row else None


async def insert_voter(data: dict[str, Any]) -> dict[str, Any]:
    payload = {c: data[c] for c in VOTER_COLUMNS if c in data}
    now = datetime.now(UTC).isoformat()
    payload.setdefault("created_at", now)
    payload.setdefault("updated_at", now)
    async with _session_factory()() as db:
        await db.execute(voters.insert().values(**payload))
        await db.commit()
    row = await get_voter(str(payload["id"]))
    assert row is not None
    return row


async def update_voter(voter_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {k: v for k, v in fields.items() if k in VOTER_COLUMNS and k != "id" and v is not None}
    if not allowed:
        return await get_voter(voter_id)
    allowed["updated_at"] = datetime.now(UTC).isoformat()
    async with _session_factory()() as db:
        await db.execute(voters.update().where(voters.c.id == voter_id).values(**allowed))
        await db.commit()
    return await get_voter(voter_id)


async def all_voters() -> list[dict[str, Any]]:
    rows, _ = await list_voters(limit=100_000, offset=0)
    return rows


async def insert_whatsapp_message(data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    payload = {
        "id": data["id"],
        "voter_id": data["voter_id"],
        "variant": data["variant"],
        "message_text": data["message_text"],
        "style": data.get("style", ""),
        "personalization_score": float(data.get("personalization_score") or 0),
        "created_at": data.get("created_at") or now,
        "scheduled_at": data.get("scheduled_at"),
        "sent_at": data.get("sent_at"),
        "campaign_topic": data.get("campaign_topic", ""),
    }
    async with _session_factory()() as db:
        await db.execute(whatsapp_messages.insert().values(**payload))
        await db.commit()
    return payload


async def list_whatsapp_messages(voter_id: str) -> list[dict[str, Any]]:
    async with _session_factory()() as db:
        rows = (
            await db.execute(
                select(whatsapp_messages)
                .where(whatsapp_messages.c.voter_id == voter_id)
                .order_by(whatsapp_messages.c.created_at.desc())
            )
        ).mappings().all()
        return [dict(r) for r in rows]


async def insert_turnout_prediction(data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    payload = {
        "id": data["id"],
        "scope": data.get("scope", ""),
        "predicted_turnout": float(data.get("predicted_turnout") or 0),
        "ci_lower": float(data.get("ci_lower") or 0),
        "ci_upper": float(data.get("ci_upper") or 0),
        "simulations": int(data.get("simulations") or 10000),
        "generated_at": data.get("generated_at") or now,
        "parameters": data.get("parameters", ""),
        "result_json": data.get("result_json", ""),
    }
    async with _session_factory()() as db:
        await db.execute(turnout_predictions.insert().values(**payload))
        await db.commit()
    return payload
