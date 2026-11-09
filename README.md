# domus-economy

Gemeinsamer, **deterministischer** Wirtschafts-Kern für die beiden Domus-Velata-Bots:

- **Alfred** → Dukaten im öffentlichen Haus
- **Mistress Vale** → dieselben Dukaten hinter dem Schleier (nur verifizierte Mitglieder)

Kein LLM, keine Discord-Abhängigkeit — reine Kontostände, Transaktionen, Regeln.
Beide Bots importieren dieses Package und gehen auf **dieselbe** Postgres
(`ECONOMY_DATABASE_URL`, getrennt von den Bot-eigenen DBs).

Konzept & Werte: `alfred-der-butler/docs/waehrungssystem.md`
Umsetzungs-Briefing: `alfred-der-butler/docs/aufgabe-waehrungssystem.md`

## Einbinden

In `requirements.txt` beider Bots:

```
domus-economy @ git+https://github.com/Halvar90/domus-economy.git@main
```

Beim Bot-Start:

```python
import os
from domus_economy import db
await db.connect(os.environ["ECONOMY_DATABASE_URL"])   # führt Migrationen aus
```

## Module

| Modul | Zweck |
|---|---|
| `db` | asyncpg-Pool, Migrationen |
| `config` | Tuning-Werte (DB-überschreibbar, `/oekonomie config`) |
| `wallets` | `balance`, `credit`, `debit` (atomar), `transfer`, `journal` |
| `faucets` | `award_message`, `award_voice`, `award_veil` (Dukaten), `claim_daily`, `milestone` |
| `shop` | `CATALOG`, `purchase()` (async-Kontextmanager), `refund` |
| `roles` | `grant`, `due`, `mark_removed` (Scheduler entfernt abgelaufene Zeit-Rollen) |
| `spotlight` | `ensure_state`, `rotate(scope, eligible_online)` — Round-Robin-Ehrenplatz |
| `vitrine` | Datengrundlage fürs Spotlight-Embed (Bot rendert) |
| `boosters` | `grant_monthly` — Dukaten-Stipendium, doppelgutschrift-sicher |
| `markers` | permanente, verdiente Marker (nicht kaufbar) |

## Leitplanken (im Code erzwungen)

- Nur `debit` mit bedingtem `WHERE currency >= betrag` — nie unter 0.
- Es gibt nur eine Währung. Schleier-Zugang und -Käufe prüfen weiterhin die Verifikation.
- Migration `002_single_currency.sql` führt vorhandene Siegel-Guthaben einmalig 1:1 in Dukaten über; alte Buchungen bleiben für Audit-Zwecke erhalten.
- Jede Bewegung schreibt eine `transactions`-Zeile.
- Scheduler-Jobs (Rotation, Ablauf, Stipendium) laufen **nur in Alfreds Prozess**.
- Kein Echtgeld-Bezug, kein öffentliches Leaderboard, Zugang nie an Währung.
