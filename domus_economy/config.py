"""
domus_economy.config — Tuning-Parameter.

Startwerte aus docs/waehrungssystem.md. Zur Laufzeit über `economy_config`
(DB) überschreibbar — `/oekonomie config`. `get()` liest DB, fällt auf DEFAULTS
zurück. Werte werden 60 s gecacht, damit nicht jede Nachricht die DB fragt.
"""

from __future__ import annotations

import json
import time
from typing import Any

from . import db

# ── Startwerte (Zeitzone-Bezug überall: Europe/Berlin) ───────────────
DEFAULTS: dict[str, Any] = {
    # Ehrenplatz-Rotation
    "rotation_interval_min": 10,
    # Faucets — Dukaten
    "msg_dukaten": 2,            # pro gezählter Nachricht
    "msg_cooldown_s": 60,
    "msg_cap_day": 100,
    "voice_dukaten_min": 1,      # pro Minute (nur ≥ 2 ungemutet, wie ansehen.py)
    "voice_cap_day": 120,
    "gunst_dukaten": 50,         # /gunst täglich
    # Faucet — Siegel (bewusst knapp)
    "veil_siegel": 1,
    "veil_cooldown_s": 180,
    "veil_cap_day": 15,
    # Booster
    "booster_multiplier": 1.5,   # auf Dukaten-Faucets
    "siegel_stipend": 30,        # pro Monat, nur verifizierte Booster
    # Tausch
    "exchange_siegel_to_dukaten": 10,   # 1 Siegel → 10 Dukaten
    # Peer
    "gift_cap_day": 100,         # je Währung, pro Tag verschenkbar
    # Zeit-Rollen
    "timed_role_days": 7,
}


class _Cache:
    def __init__(self) -> None:
        self.at = 0.0
        self.data: dict[str, Any] = {}


_cache = _Cache()
_TTL = 60.0


async def _load() -> dict[str, Any]:
    if time.monotonic() - _cache.at < _TTL:
        return _cache.data
    rows = await db.pool().fetch("SELECT key, value FROM economy_config")
    _cache.data = {r["key"]: json.loads(r["value"]) for r in rows}
    _cache.at = time.monotonic()
    return _cache.data


async def get(key: str) -> Any:
    if key not in DEFAULTS:
        raise KeyError(f"unbekannter Config-Key: {key}")
    return (await _load()).get(key, DEFAULTS[key])


async def get_all() -> dict[str, Any]:
    live = await _load()
    return {k: live.get(k, v) for k, v in DEFAULTS.items()}


async def set_value(key: str, value: Any) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"unbekannter Config-Key: {key}")
    # Typ grob an den Default angleichen
    default = DEFAULTS[key]
    if isinstance(default, bool):
        value = bool(value)
    elif isinstance(default, int):
        value = int(value)
    elif isinstance(default, float):
        value = float(value)
    await db.pool().execute(
        "INSERT INTO economy_config (key, value) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (key) DO UPDATE SET value = $2::jsonb",
        key, json.dumps(value))
    _cache.at = 0.0
