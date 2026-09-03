"""
domus_economy.boosters — monatliches Siegel-Stipendium für verifizierte Booster.

Der Bot ruft grant_monthly() für jedes verifizierte Booster-Mitglied auf
(Scheduler, monatlich). Doppelgutschrift-Schutz über booster_stipend.last_granted
(Monat). Der 1,5×-Faucet-Multiplikator steckt in faucets.py, nicht hier.
"""

from __future__ import annotations

import datetime as dt

from . import config, db
from .wallets import _credit


async def grant_monthly(user_id: int) -> int:
    """Schreibt das Stipendium gut, sofern in diesem Monat noch nicht geschehen.
    Gibt den gutgeschriebenen Betrag zurück (0 = schon gehabt)."""
    amount = int(await config.get("siegel_stipend"))
    month_start = dt.date.today().replace(day=1)
    async with db.pool().acquire() as con, con.transaction():
        row = await con.fetchrow(
            "SELECT last_granted FROM booster_stipend WHERE user_id = $1 FOR UPDATE", user_id)
        if row and row["last_granted"] >= month_start:
            return 0
        await con.execute(
            "INSERT INTO booster_stipend (user_id, last_granted) VALUES ($1, $2) "
            "ON CONFLICT (user_id) DO UPDATE SET last_granted = $2", user_id, month_start)
        await _credit(con, user_id, "siegel", amount, "booster_stipend")
    return amount
