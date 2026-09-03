"""
domus_economy.shop — Katalog + Kauf.

Katalog als Config-Struktur (kein DB-Overhead). `purchase()` ist ein
async-Kontextmanager: er bucht atomar ab und legt ggf. die timed_roles-Zeile an,
DANN führt der Bot im `with`-Block den Discord-Effekt aus (Rolle/Kanal/Pin).
Wirft der Effekt → Transaktion rollt zurück, nichts wurde bezahlt.

Alfreds Dukaten-Laden dupliziert bewusst NICHT die Ansehen-Perks
(/meine-farbe, /meine-rolle, /mein-titel bleiben Level-Freischaltungen).
"""

from __future__ import annotations

import datetime as dt
from contextlib import asynccontextmanager
from dataclasses import dataclass

from . import db
from .wallets import EconomyError, _credit, _debit

# id → Spezifikation
CATALOG: dict[str, dict] = {
    # ── Dukaten-Laden (öffentliches Haus) ──────────────────────────
    "illuster": {
        "name": "Dauer-Rang »Illuster«", "scope": "haus",
        "cost": {"dukaten": 400}, "duration_days": 7, "tier": "illuster",
        "effect": "role", "rotation_eligible": True,
        "desc": "hoisted goldene Rolle; nimmt an der Ehrenplatz-Rotation teil"},
    "rollen_icon": {
        "name": "Rollen-Icon", "scope": "haus",
        "cost": {"dukaten": 200}, "duration_days": 7, "tier": "icon",
        "effect": "role",
        "desc": "Icon neben dem Namen (Server braucht Boost-Level 2)"},
    "beitrag_pin_haus": {
        "name": "Hervorgehobener Beitrag", "scope": "haus",
        "cost": {"dukaten": 80}, "duration_days": None, "effect": "post_pin",
        "desc": "Pin/Hervorhebung in den Kabinetten"},
    "separee_haus": {
        "name": "Öffentliches Séparée", "scope": "haus",
        "cost": {"dukaten": 250}, "duration_days": None, "effect": "separee",
        "hours": 48,
        "desc": "temporärer Raum zum Gastgeben (Filmabend, Spielrunde)"},
    "alfred_zuwendung": {
        "name": "Alfred-Zuwendung", "scope": "haus",
        "cost": {"dukaten": 60}, "duration_days": None, "effect": "bot_attention",
        "desc": "eine kosmetische Aufmerksamkeit des Butlers"},

    # ── Siegel-Laden (hinter dem Schleier) ─────────────────────────
    "schleier_rang": {
        "name": "Schleier-Dauer-Rang", "scope": "schleier",
        "cost": {"siegel": 60}, "duration_days": 7, "tier": "schleier_rang",
        "effect": "role", "rotation_eligible": True,
        "desc": "hoisted Rolle im Schleier-Bereich; nimmt an der Schleier-Rotation teil"},
    "schleier_kosmetik": {
        "name": "Schleier-Kosmetik (Titel/Farbe)", "scope": "schleier",
        "cost": {"siegel": 40}, "duration_days": 7, "tier": "kosmetik",
        "effect": "role",
        "desc": "Titel/Farbe, die es ausschließlich hinter dem Schleier gibt"},
    "galerie_pin": {
        "name": "Priorität in der Galerie", "scope": "schleier",
        "cost": {"siegel": 20}, "duration_days": None, "effect": "post_pin",
        "desc": "Hervorhebung eines Galerie-Beitrags"},
    "separee_schleier": {
        "name": "Privates Schleier-Séparée", "scope": "schleier",
        "cost": {"siegel": 50}, "duration_days": None, "effect": "separee",
        "hours": 24,
        "desc": "eine kuratierte Runde hinter dem Schleier — nur ein Raum, keine Szene"},
    "vale_zuwendung": {
        "name": "Vale-Zuwendung", "scope": "schleier",
        "cost": {"siegel": 15}, "duration_days": None, "effect": "bot_attention",
        "desc": "eine kosmetische Aufmerksamkeit der Hausherrin"},

    # ── Mischpreis — der Ort, an dem beide Währungen zusammenkommen ──
    "prestige": {
        "name": "Top-Prestige-Marker", "scope": "schleier",
        "cost": {"dukaten": 500, "siegel": 50}, "duration_days": 14, "tier": "prestige",
        "effect": "role", "rotation_eligible": True,
        "desc": "höchster kombinierter Sichtbarkeits-Rang"},
}


@dataclass
class Receipt:
    item_id: str
    item: dict
    timed_role_id: int | None
    expires_at: dt.datetime | None


def catalog(scope: str | None = None) -> list[tuple[str, dict]]:
    return [(k, v) for k, v in CATALOG.items() if scope is None or v["scope"] == scope]


@asynccontextmanager
async def purchase(user_id: int, item_id: str, *, role_id: int | None = None):
    """Atomarer Kauf. Der Bot führt im with-Block den Discord-Effekt aus;
    wirft er, wird nichts abgebucht."""
    item = CATALOG.get(item_id)
    if item is None:
        raise EconomyError(f"unbekannter Artikel: {item_id}")
    now = dt.datetime.now(dt.timezone.utc)
    expires = now + dt.timedelta(days=item["duration_days"]) if item.get("duration_days") else None

    async with db.pool().acquire() as con, con.transaction():
        for cur, amt in item["cost"].items():
            await _debit(con, user_id, cur, amt, "shop_purchase", meta={"item": item_id})
        tr_id = None
        if item.get("duration_days"):
            if role_id is None:
                raise EconomyError(f"{item_id}: role_id fehlt")
            tr_id = await con.fetchval(
                "INSERT INTO timed_roles (user_id, role_id, tier, scope, expires_at) "
                "VALUES ($1,$2,$3,$4,$5) RETURNING id",
                user_id, role_id, item["tier"], item["scope"], expires)
        # Der Bot macht jetzt den Effekt. Exception hier → Rollback von allem.
        yield Receipt(item_id, item, tr_id, expires)


async def refund(user_id: int, item_id: str, *, reason: str = "admin_refund") -> None:
    """Admin: einen Kauf rückgängig machen (Geld zurück, timed_role deaktivieren)."""
    item = CATALOG.get(item_id)
    if item is None:
        raise EconomyError(f"unbekannter Artikel: {item_id}")
    async with db.pool().acquire() as con, con.transaction():
        for cur, amt in item["cost"].items():
            await _credit(con, user_id, cur, amt, reason, meta={"item": item_id})
        await con.execute(
            "UPDATE timed_roles SET active = false "
            "WHERE user_id = $1 AND tier = $2 AND active",
            user_id, item.get("tier", "—"))


async def my_timed_roles(user_id: int) -> list[dict]:
    rows = await db.pool().fetch(
        "SELECT role_id, tier, scope, expires_at FROM timed_roles "
        "WHERE user_id = $1 AND active ORDER BY expires_at", user_id)
    return [dict(r) for r in rows]
