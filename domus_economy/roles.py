"""
domus_economy.roles — zeitlich begrenzte Rollen.

Der Kauf legt die timed_roles-Zeile an (shop.purchase). Hier: Admin-Grant,
Ablauf-Abfrage für den Scheduler, Deaktivierung nach dem Entfernen im Discord.
Die eigentliche Discord-Rollenvergabe/-entfernung macht der Bot.
"""

from __future__ import annotations

import datetime as dt

from . import db


async def grant(user_id: int, role_id: int, tier: str, scope: str, days: int) -> dt.datetime:
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)
    await db.pool().execute(
        "INSERT INTO timed_roles (user_id, role_id, tier, scope, expires_at) "
        "VALUES ($1,$2,$3,$4,$5)", user_id, role_id, tier, scope, expires)
    return expires


async def due() -> list[dict]:
    """Abgelaufene, noch aktive Zeit-Rollen — der Scheduler entfernt sie im Discord."""
    rows = await db.pool().fetch(
        "SELECT id, user_id, role_id, tier, scope FROM timed_roles "
        "WHERE active AND expires_at <= now() ORDER BY expires_at LIMIT 200")
    return [dict(r) for r in rows]


async def mark_removed(ids: list[int]) -> None:
    if ids:
        await db.pool().execute(
            "UPDATE timed_roles SET active = false WHERE id = ANY($1::bigint[])", ids)


async def still_holds(user_id: int, role_id: int) -> bool:
    """Hat die Person noch eine AKTIVE Zeit-Rolle mit dieser role_id?
    (Für den Fall, dass zwei Käufe dieselbe Rolle betrafen.)"""
    return bool(await db.pool().fetchval(
        "SELECT 1 FROM timed_roles WHERE user_id = $1 AND role_id = $2 AND active LIMIT 1",
        user_id, role_id))


async def revoke(user_id: int, tier: str) -> list[int]:
    """Admin: eine Tier-Rolle vorzeitig beenden. Gibt die betroffenen role_ids zurück."""
    rows = await db.pool().fetch(
        "UPDATE timed_roles SET active = false "
        "WHERE user_id = $1 AND tier = $2 AND active RETURNING role_id", user_id, tier)
    return [r["role_id"] for r in rows]
