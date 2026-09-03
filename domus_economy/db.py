"""
domus_economy.db — asyncpg-Pool + Migrationen.

Jeder Bot-Prozess (Alfred, Vale) ruft beim Start `await db.connect(url)` mit
ECONOMY_DATABASE_URL. Eigener Pool je Prozess. Ein Pool wird gecacht.
"""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

log = logging.getLogger("domus_economy.db")

_MIG = Path(__file__).parent / "migrations"
_pool: asyncpg.Pool | None = None


async def connect(url: str, *, run_migrations: bool = True) -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    _pool = await asyncpg.create_pool(url, min_size=1, max_size=5,
                                      command_timeout=30)
    if run_migrations:
        await _migrate()
    log.info("domus_economy: DB verbunden.")
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("domus_economy.db.connect() wurde nicht aufgerufen.")
    return _pool


async def _migrate() -> None:
    files = sorted(_MIG.glob("*.sql"))
    async with _pool.acquire() as con:
        for f in files:
            await con.execute(f.read_text(encoding="utf-8"))
    log.info("domus_economy: %d Migration(en) angewandt.", len(files))
