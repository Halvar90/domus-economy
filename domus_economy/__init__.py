"""
domus_economy — gemeinsamer Wirtschafts-Kern für Alfred (Dukaten) und Vale (Siegel).

Deterministisch, kein LLM. Eigene Postgres (ECONOMY_DATABASE_URL).
Konzept: docs/waehrungssystem.md · Umsetzung: docs/aufgabe-waehrungssystem.md.

Nutzung:
    from domus_economy import db, wallets, faucets, shop, roles, spotlight, boosters, markers, config
    await db.connect(os.environ["ECONOMY_DATABASE_URL"])
"""

from . import (  # noqa: F401
    boosters, config, db, faucets, markers, roles, shop, spotlight, vitrine, wallets,
)
from .wallets import EconomyError, InsufficientFunds  # noqa: F401
from .faucets import AlreadyClaimed  # noqa: F401

__version__ = "0.1.0"
