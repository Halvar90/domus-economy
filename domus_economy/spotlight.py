"""
domus_economy.spotlight — der rotierende Ehrenplatz (je Sphäre eine Rolle).

Round-Robin NUR unter Online-Trägern des Dauer-Rangs (Booster NICHT bevorzugt).
Der Bot sammelt die berechtigten+online IDs (Presence-Intent!) und ruft rotate().
Zurück kommt, welche Rolle wem zu geben/nehmen ist — Discord macht der Bot.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from . import db, markers

_MARKER_THRESHOLD = 10   # „Ehrenplatz 10× gehalten"


@dataclass
class RotationResult:
    remove_from: int | None      # dem die Rolle genommen wird
    add_to: int | None           # der sie bekommt
    unchanged: bool
    marker_earned_by: int | None  # falls jemand gerade den 10×-Marker bekam


async def ensure_state(scope: str, spotlight_role_id: int) -> None:
    await db.pool().execute(
        "INSERT INTO spotlight_state (scope, spotlight_role_id) VALUES ($1, $2) "
        "ON CONFLICT (scope) DO UPDATE SET spotlight_role_id = $2",
        scope, spotlight_role_id)


async def current(scope: str) -> dict | None:
    row = await db.pool().fetchrow(
        "SELECT spotlight_role_id, current_holder, last_rotated_at "
        "FROM spotlight_state WHERE scope = $1", scope)
    return dict(row) if row else None


async def rotate(scope: str, eligible_online: list[int]) -> RotationResult:
    eligible = sorted(set(int(x) for x in eligible_online))
    async with db.pool().acquire() as con, con.transaction():
        row = await con.fetchrow(
            "SELECT current_holder, last_holder FROM spotlight_state "
            "WHERE scope = $1 FOR UPDATE", scope)
        if row is None:
            raise RuntimeError(f"spotlight_state fehlt für {scope} — ensure_state() zuerst.")
        cur, last = row["current_holder"], row["last_holder"]

        if not eligible:
            if cur is not None:
                await con.execute(
                    "UPDATE spotlight_state SET current_holder = NULL, last_rotated_at = now() "
                    "WHERE scope = $1", scope)
                return RotationResult(cur, None, False, None)
            return RotationResult(None, None, True, None)

        if last is None:
            nxt = eligible[0]
        elif last in eligible:
            nxt = eligible[(eligible.index(last) + 1) % len(eligible)]
        else:
            # last ist offline gegangen — dort weitermachen, wo er im Ring stünde
            nxt = eligible[bisect.bisect_right(eligible, last) % len(eligible)]

        if nxt == cur:
            return RotationResult(None, None, True, None)

        await con.execute(
            "UPDATE spotlight_state SET current_holder = $2, last_holder = $2, "
            "last_rotated_at = now() WHERE scope = $1", scope, nxt)

    earned = await markers.bump(nxt, f"ehrenplatz_{scope}", _MARKER_THRESHOLD,
                                "ehrenplatz_10x")
    return RotationResult(cur, nxt, False, nxt if earned else None)
