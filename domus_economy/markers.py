"""
domus_economy.markers — permanente, verdiente Marker (nicht kaufbar, nicht handelbar).
"""

from __future__ import annotations

from . import db


async def award(user_id: int, marker: str) -> bool:
    """True, wenn NEU vergeben."""
    got = await db.pool().fetchval(
        "INSERT INTO markers (user_id, marker) VALUES ($1, $2) "
        "ON CONFLICT DO NOTHING RETURNING id", user_id, marker)
    return got is not None


async def has(user_id: int, marker: str) -> bool:
    return bool(await db.pool().fetchval(
        "SELECT 1 FROM markers WHERE user_id = $1 AND marker = $2", user_id, marker))


async def list_for(user_id: int) -> list[str]:
    rows = await db.pool().fetch(
        "SELECT marker FROM markers WHERE user_id = $1 ORDER BY earned_at", user_id)
    return [r["marker"] for r in rows]


async def bump(user_id: int, metric: str, threshold: int, marker: str) -> bool:
    """Zähler +1. Erreicht er die Schwelle und der Marker fehlt noch → vergeben.
    Gibt True zurück, wenn der Marker in diesem Aufruf NEU vergeben wurde."""
    async with db.pool().acquire() as con, con.transaction():
        n = await con.fetchval(
            "INSERT INTO marker_progress (user_id, metric, n) VALUES ($1, $2, 1) "
            "ON CONFLICT (user_id, metric) DO UPDATE SET n = marker_progress.n + 1 "
            "RETURNING n", user_id, metric)
        if n >= threshold:
            got = await con.fetchval(
                "INSERT INTO markers (user_id, marker) VALUES ($1, $2) "
                "ON CONFLICT DO NOTHING RETURNING id", user_id, marker)
            return got is not None
    return False
