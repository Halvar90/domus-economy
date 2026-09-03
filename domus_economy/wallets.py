"""
domus_economy.wallets — Kontostand, Gutschrift, Abbuchung, Tausch.

Jede Bewegung schreibt ATOMAR eine transactions-Zeile. Abbuchung nie
"lesen-prüfen-schreiben", sondern bedingtes UPDATE (dukaten >= betrag).
"""

from __future__ import annotations

import json

from . import config, db

CURRENCIES = ("dukaten", "siegel")


class EconomyError(Exception):
    pass


class InsufficientFunds(EconomyError):
    def __init__(self, currency: str, have: int, need: int):
        self.currency, self.have, self.need = currency, have, need
        super().__init__(f"{have} {currency}, gebraucht {need}")


def _check_currency(c: str) -> None:
    if c not in CURRENCIES:
        raise EconomyError(f"unbekannte Währung: {c}")


async def _ensure_wallet(con, user_id: int) -> None:
    await con.execute(
        "INSERT INTO wallets (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)


async def balance(user_id: int) -> dict[str, int]:
    row = await db.pool().fetchrow(
        "SELECT dukaten, siegel FROM wallets WHERE user_id = $1", user_id)
    return {"dukaten": row["dukaten"], "siegel": row["siegel"]} if row \
        else {"dukaten": 0, "siegel": 0}


async def _credit(con, user_id: int, currency: str, amount: int, reason: str,
                  counterparty_id: int | None = None, meta: dict | None = None) -> int:
    """Gutschrift innerhalb einer bestehenden Transaktion. amount > 0."""
    if amount <= 0:
        raise EconomyError("Gutschrift muss > 0 sein.")
    await _ensure_wallet(con, user_id)
    new = await con.fetchval(
        f"UPDATE wallets SET {currency} = {currency} + $2, updated_at = now() "
        f"WHERE user_id = $1 RETURNING {currency}", user_id, amount)
    await con.execute(
        "INSERT INTO transactions (user_id, currency, amount, reason, counterparty_id, meta) "
        "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
        user_id, currency, amount, reason, counterparty_id,
        json.dumps(meta) if meta else None)
    return new


async def _debit(con, user_id: int, currency: str, amount: int, reason: str,
                 counterparty_id: int | None = None, meta: dict | None = None) -> int:
    """Bedingte Abbuchung innerhalb einer Transaktion. Wirft InsufficientFunds."""
    if amount <= 0:
        raise EconomyError("Abbuchung muss > 0 sein.")
    await _ensure_wallet(con, user_id)
    new = await con.fetchval(
        f"UPDATE wallets SET {currency} = {currency} - $2, updated_at = now() "
        f"WHERE user_id = $1 AND {currency} >= $2 RETURNING {currency}",
        user_id, amount)
    if new is None:
        have = await con.fetchval(
            f"SELECT {currency} FROM wallets WHERE user_id = $1", user_id) or 0
        raise InsufficientFunds(currency, have, amount)
    await con.execute(
        "INSERT INTO transactions (user_id, currency, amount, reason, counterparty_id, meta) "
        "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
        user_id, currency, -amount, reason, counterparty_id,
        json.dumps(meta) if meta else None)
    return new


# ── öffentliche Einzeloperationen (eigene Transaktion) ───────────────

async def credit(user_id: int, currency: str, amount: int, reason: str,
                 counterparty_id: int | None = None, meta: dict | None = None) -> int:
    _check_currency(currency)
    async with db.pool().acquire() as con, con.transaction():
        return await _credit(con, user_id, currency, amount, reason, counterparty_id, meta)


async def debit(user_id: int, currency: str, amount: int, reason: str,
                counterparty_id: int | None = None, meta: dict | None = None) -> int:
    _check_currency(currency)
    async with db.pool().acquire() as con, con.transaction():
        return await _debit(con, user_id, currency, amount, reason, counterparty_id, meta)


async def transfer(from_id: int, to_id: int, currency: str, amount: int) -> None:
    """Peer-Geschenk. Prüft Tages-Limit (config gift_cap_day)."""
    _check_currency(currency)
    if from_id == to_id:
        raise EconomyError("An sich selbst geht nicht.")
    cap = await config.get("gift_cap_day")
    async with db.pool().acquire() as con, con.transaction():
        given = await con.fetchval(
            "INSERT INTO peer_gifts (user_id, day, given) VALUES ($1, CURRENT_DATE, 0) "
            "ON CONFLICT (user_id, day) DO UPDATE SET given = peer_gifts.given "
            "RETURNING given", from_id)
        if given + amount > cap:
            raise EconomyError(f"Tageslimit erreicht ({given}/{cap} {currency} verschenkt).")
        await _debit(con, from_id, currency, amount, "gift_out", to_id)
        await _credit(con, to_id, currency, amount, "gift_in", from_id)
        await con.execute(
            "UPDATE peer_gifts SET given = given + $2 WHERE user_id = $1 AND day = CURRENT_DATE",
            from_id, amount)


async def exchange_siegel_to_dukaten(user_id: int, siegel_amount: int) -> dict[str, int]:
    """Nur diese Richtung. Kurs aus config. Gibt neue Stände zurück."""
    if siegel_amount <= 0:
        raise EconomyError("Betrag muss > 0 sein.")
    rate = await config.get("exchange_siegel_to_dukaten")
    dukaten = siegel_amount * int(rate)
    async with db.pool().acquire() as con, con.transaction():
        await _debit(con, user_id, "siegel", siegel_amount, "exchange",
                     meta={"to": "dukaten", "rate": rate})
        await _credit(con, user_id, "dukaten", dukaten, "exchange",
                      meta={"from": "siegel", "rate": rate})
    return await balance(user_id)


async def admin_set(user_id: int, currency: str, amount: int) -> int:
    _check_currency(currency)
    if amount < 0:
        raise EconomyError("Kein negativer Kontostand.")
    async with db.pool().acquire() as con, con.transaction():
        await _ensure_wallet(con, user_id)
        cur = await con.fetchval(
            f"SELECT {currency} FROM wallets WHERE user_id = $1", user_id) or 0
        delta = amount - cur
        if delta:
            await con.execute(
                f"UPDATE wallets SET {currency} = $2, updated_at = now() WHERE user_id = $1",
                user_id, amount)
            await con.execute(
                "INSERT INTO transactions (user_id, currency, amount, reason) "
                "VALUES ($1, $2, $3, 'admin_set')", user_id, currency, delta)
    return amount


async def journal(user_id: int, limit: int = 25) -> list[dict]:
    rows = await db.pool().fetch(
        "SELECT currency, amount, reason, counterparty_id, meta, created_at "
        "FROM transactions WHERE user_id = $1 ORDER BY id DESC LIMIT $2", user_id, limit)
    return [dict(r) for r in rows]
