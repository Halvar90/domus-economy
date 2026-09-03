"""
domus_economy.vitrine — Datengrundlage fürs Spotlight-Embed.

Das Package bleibt discord-frei: hier kommt nur ein Daten-Dict zurück, das
Embed baut der Bot (er hat Avatar/Namen/Kanäle).
"""

from __future__ import annotations

from . import db, spotlight  # noqa: F401  (spotlight re-export für Bequemlichkeit)

SCOPE_LABEL = {"haus": "Zur Rechten des Hauses", "schleier": "Zur Rechten hinter dem Schleier"}


async def state(scope: str) -> dict:
    cur = await spotlight.current(scope)
    return {
        "scope": scope,
        "label": SCOPE_LABEL.get(scope, scope),
        "holder": cur["current_holder"] if cur else None,
        "since": cur["last_rotated_at"] if cur else None,
    }


async def holders(scope: str) -> list[int]:
    """Alle mit einer aktiven rotationsberechtigten Zeit-Rolle in dieser Sphäre."""
    tiers = ("illuster", "prestige") if scope == "haus" else ("schleier_rang", "prestige")
    rows = await db.pool().fetch(
        "SELECT DISTINCT user_id FROM timed_roles "
        "WHERE active AND scope = $1 AND tier = ANY($2::text[])", scope, list(tiers))
    return [r["user_id"] for r in rows]
