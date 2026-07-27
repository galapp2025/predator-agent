"""SQLite persistence for BlackOpps voters."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import aiosqlite

# Repo root: predator-agent/  (…/backend/app/db.py → parents[2])
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DB_PATH = Path(os.getenv("BLACKOPPS_DB", str(DATA_DIR / "blackopps.db")))

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS voters (
    id TEXT PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    city TEXT DEFAULT '',
    neighborhood TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    email TEXT DEFAULT '',
    support_score REAL DEFAULT 0.5,
    turnout_history REAL DEFAULT 0.0,
    gotv_category TEXT DEFAULT '',
    gotv_priority INTEGER DEFAULT 0,
    gotv_channel TEXT DEFAULT '',
    gotv_frequency TEXT DEFAULT '',
    gotv_message TEXT DEFAULT '',
    enriched_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_voters_name ON voters(first_name, last_name);
CREATE INDEX IF NOT EXISTS idx_voters_category ON voters(gotv_category);
"""

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


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


async def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()


async def get_connection() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def list_voters(
    *,
    limit: int = 100,
    offset: int = 0,
    category: str | None = None,
    search: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    clauses: list[str] = []
    params: list[Any] = []
    if category:
        clauses.append("LOWER(gotv_category) = LOWER(?)")
        params.append(category)
    if search:
        clauses.append(
            "(first_name LIKE ? OR last_name LIKE ? OR city LIKE ? OR phone LIKE ?)"
        )
        like = f"%{search}%"
        params.extend([like, like, like, like])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(f"SELECT COUNT(*) AS c FROM voters {where}", params)
        total = int((await cur.fetchone())["c"])
        cur = await db.execute(
            f"""
            SELECT * FROM voters {where}
            ORDER BY gotv_priority DESC, created_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        )
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows], total


async def get_voter(voter_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM voters WHERE id = ?", (voter_id,))
        row = await cur.fetchone()
        return _row_to_dict(row) if row else None


async def find_by_name(first_name: str, last_name: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM voters WHERE LOWER(first_name)=LOWER(?) AND LOWER(last_name)=LOWER(?) LIMIT 1",
            (first_name.strip(), last_name.strip()),
        )
        row = await cur.fetchone()
        return _row_to_dict(row) if row else None


async def insert_voter(data: dict[str, Any]) -> dict[str, Any]:
    cols = [c for c in VOTER_COLUMNS if c in data]
    placeholders = ", ".join("?" for _ in cols)
    col_sql = ", ".join(cols)
    values = [data[c] for c in cols]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(f"INSERT INTO voters ({col_sql}) VALUES ({placeholders})", values)
        await db.commit()
        cur = await db.execute("SELECT * FROM voters WHERE id = ?", (data["id"],))
        row = await cur.fetchone()
        assert row is not None
        return _row_to_dict(row)


async def update_voter(voter_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {k: v for k, v in fields.items() if k in VOTER_COLUMNS and k != "id" and v is not None}
    if not allowed:
        return await get_voter(voter_id)
    allowed["updated_at"] = "datetime('now')"
    # Build SET carefully — datetime('now') as SQL expression
    sets: list[str] = []
    params: list[Any] = []
    for k, v in allowed.items():
        if k == "updated_at":
            sets.append("updated_at = datetime('now')")
        else:
            sets.append(f"{k} = ?")
            params.append(v)
    params.append(voter_id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(f"UPDATE voters SET {', '.join(sets)} WHERE id = ?", params)
        await db.commit()
        cur = await db.execute("SELECT * FROM voters WHERE id = ?", (voter_id,))
        row = await cur.fetchone()
        return _row_to_dict(row) if row else None


async def all_voters() -> list[dict[str, Any]]:
    rows, _ = await list_voters(limit=100_000, offset=0)
    return rows
