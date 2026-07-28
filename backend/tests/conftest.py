import pytest

from app import db


@pytest.fixture(autouse=True)
async def _ensure_db_schema():
    await db.init_db()
