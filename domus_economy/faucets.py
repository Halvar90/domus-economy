"""
domus_economy.faucets — woher die Währung kommt.

award_message / award_voice speisen Dukaten; ansehen.py (Alfred) ruft sie beim
XP-Vergeben mit auf (Entscheidung „gekoppelt"). award_veil speist Siegel, nur
für verifizierte Mitglieder hinterm Schleier. claim_daily = /gunst.

Cooldowns + Tages-Caps in earn_cooldowns, alles atomar. Tages-Grenze: Europe/Berlin.
"""

from __future__ import annotations

import datetime as dt

from . import config, db
from .wallets import EconomyError, _credit

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Berlin")
except Exception:  # noqa: BLE001
    _TZ = dt.timezone(dt.timedelta(hours=1))


def _today() -> dt.date:
    return dt.datetime.now(_TZ).date()


class AlreadyClaimed(EconomyError):
    def __init__(self, next_at: dt.datetime):
        self.next_at = next_at
        super().__init__("heute schon abgeholt")


async def _faucet(con, user_id: int, faucet: str, amount: int, cap: int,
                  cooldown_s: int, reason: str) -> int:
    """Kern: Cooldown + Tages-Cap prüfen, gutschreiben, earn_cooldowns fortschreiben.
    Gibt den TATSÄCHLICH gutgeschriebenen Betrag zurück (0 = nichts)."""
    now = dt.datetime.now(dt.timezone.utc)
    today = _today()
    row = await con.fetchrow(
        "SELECT last_at, day, day_sum FROM earn_cooldowns "
        "WHERE user_id = $1 AND faucet = $2 FOR UPDATE", user_id, faucet)
    day_sum = 0
    if row:
        if cooldown_s and row["last_at"] and \
           (now - row["last_at"]).total_seconds() < cooldown_s:
            return 0
        day_sum = row["day_sum"] if row["day"] == today else 0
    room = max(0, cap - day_sum)
    grant = min(amount, room)
    if grant <= 0:
        # trotzdem last_at fortschreiben, damit der Cooldown greift
        await con.execute(
            "INSERT INTO earn_cooldowns (user_id, faucet, last_at, day, day_sum) "
            "VALUES ($1,$2,$3,$4,$5) ON CONFLICT (user_id, faucet) DO UPDATE "
            "SET last_at = $3, day = $4, day_sum = $5",
            user_id, faucet, now, today, day_sum)
        return 0
    await _credit(con, user_id, "dukaten" if faucet != "veil" else "siegel", grant, reason)
    await con.execute(
        "INSERT INTO earn_cooldowns (user_id, faucet, last_at, day, day_sum) "
        "VALUES ($1,$2,$3,$4,$5) ON CONFLICT (user_id, faucet) DO UPDATE "
        "SET last_at = $3, day = $4, day_sum = $5",
        user_id, faucet, now, today, day_sum + grant)
    return grant


async def award_message(user_id: int, *, is_booster: bool = False) -> int:
    base = int(await config.get("msg_dukaten"))
    amount = round(base * float(await config.get("booster_multiplier"))) if is_booster else base
    async with db.pool().acquire() as con, con.transaction():
        return await _faucet(con, user_id, "message", amount,
                             int(await config.get("msg_cap_day")),
                             int(await config.get("msg_cooldown_s")), "faucet_message")


async def award_voice(user_id: int, minutes: int, *, is_booster: bool = False) -> int:
    if minutes <= 0:
        return 0
    per = int(await config.get("voice_dukaten_min"))
    amount = minutes * per
    if is_booster:
        amount = round(amount * float(await config.get("booster_multiplier")))
    async with db.pool().acquire() as con, con.transaction():
        return await _faucet(con, user_id, "voice", amount,
                             int(await config.get("voice_cap_day")), 0, "faucet_voice")


async def award_veil(user_id: int, *, is_verified: bool) -> int:
    if not is_verified:
        return 0
    async with db.pool().acquire() as con, con.transaction():
        return await _faucet(con, user_id, "veil", int(await config.get("veil_siegel")),
                             int(await config.get("veil_cap_day")),
                             int(await config.get("veil_cooldown_s")), "faucet_veil")


async def claim_daily(user_id: int, *, is_booster: bool = False) -> int:
    """/gunst. Wirft AlreadyClaimed, wenn heute schon. Gibt den Betrag zurück."""
    base = int(await config.get("gunst_dukaten"))
    amount = round(base * float(await config.get("booster_multiplier"))) if is_booster else base
    today = _today()
    async with db.pool().acquire() as con, con.transaction():
        row = await con.fetchrow(
            "SELECT day FROM earn_cooldowns WHERE user_id = $1 AND faucet = 'daily' FOR UPDATE",
            user_id)
        if row and row["day"] == today:
            nxt = dt.datetime.combine(today + dt.timedelta(days=1), dt.time(), _TZ)
            raise AlreadyClaimed(nxt.astimezone(dt.timezone.utc))
        await _credit(con, user_id, "dukaten", amount, "claim_daily")
        await con.execute(
            "INSERT INTO earn_cooldowns (user_id, faucet, last_at, day, day_sum) "
            "VALUES ($1,'daily',now(),$2,$3) ON CONFLICT (user_id, faucet) DO UPDATE "
            "SET last_at = now(), day = $2, day_sum = $3",
            user_id, today, amount)
    return amount


async def milestone(user_id: int, key: str, currency: str, amount: int) -> int:
    """Einmalige Meilenstein-Gutschrift (Vorstellung, erster Forenbeitrag …).
    Nutzt markers als Dedup. Gibt den gutgeschriebenen Betrag zurück (0 = schon gehabt)."""
    async with db.pool().acquire() as con, con.transaction():
        got = await con.fetchval(
            "INSERT INTO markers (user_id, marker) VALUES ($1, $2) "
            "ON CONFLICT DO NOTHING RETURNING id", user_id, f"milestone:{key}")
        if got is None:
            return 0
        await _credit(con, user_id, currency, amount, "milestone", meta={"key": key})
    return amount
