"""
Integrationstest gegen eine echte Postgres.

    ECONOMY_TEST_URL=postgresql://postgres@127.0.0.1:5433/economy  python -m pytest -q
oder direkt:  python tests/test_economy.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domus_economy import boosters, config, db, faucets, markers, roles, shop, spotlight, wallets  # noqa: E402
from domus_economy.wallets import InsufficientFunds  # noqa: E402
from domus_economy.faucets import AlreadyClaimed  # noqa: E402

URL = os.environ.get("ECONOMY_TEST_URL", "postgresql://postgres@127.0.0.1:5433/economy")
A, B = 111, 222


async def _reset(pool):
    await pool.execute("""
        TRUNCATE wallets, transactions, timed_roles, spotlight_state, earn_cooldowns,
                 booster_stipend, markers, marker_progress, economy_config, peer_gifts;
    """)


async def run():
    pool = await db.connect(URL)
    await _reset(pool)
    ok = []

    # ── wallets: credit/debit atomar, nie unter 0 ──────────────────
    await wallets.credit(A, "dukaten", 100, "test")
    assert (await wallets.balance(A))["dukaten"] == 100
    await wallets.debit(A, "dukaten", 40, "test")
    assert (await wallets.balance(A))["dukaten"] == 60
    try:
        await wallets.debit(A, "dukaten", 999, "test")
        raise AssertionError("debit hätte werfen müssen")
    except InsufficientFunds:
        pass
    assert (await wallets.balance(A))["dukaten"] == 60
    ok.append("wallets credit/debit/guard")

    # ── parallele Käufe können nicht doppelt ausgeben ──────────────
    await wallets.admin_set(A, "dukaten", 100)
    results = await asyncio.gather(
        *[wallets.debit(A, "dukaten", 100, "race") for _ in range(5)],
        return_exceptions=True)
    successes = [r for r in results if not isinstance(r, Exception)]
    assert len(successes) == 1, f"nur EIN debit darf durchgehen, waren {len(successes)}"
    assert (await wallets.balance(A))["dukaten"] == 0
    ok.append("kein doppel-debit bei Race")

    # ── exchange: nur Siegel→Dukaten ──────────────────────────────
    await wallets.credit(A, "siegel", 5, "test")
    bal = await wallets.exchange_siegel_to_dukaten(A, 5)
    assert bal["siegel"] == 0 and bal["dukaten"] == 50   # Kurs 1:10
    ok.append("exchange Siegel→Dukaten (Kurs 10)")

    # ── faucets: Cooldown + Tagescap ─────────────────────────────
    await _reset(pool)
    g1 = await faucets.award_message(A)
    g2 = await faucets.award_message(A)   # sofort → Cooldown
    assert g1 == 2 and g2 == 0, (g1, g2)
    # Cap: künstlich fast voll setzen
    await pool.execute("UPDATE earn_cooldowns SET day_sum = 99, last_at = now() - interval '1 hour' "
                       "WHERE user_id=$1 AND faucet='message'", A)
    g3 = await faucets.award_message(A)
    assert g3 == 1, g3   # nur noch 1 bis zum Cap 100
    g4 = await faucets.award_message(A)
    assert g4 == 0
    ok.append("faucet Cooldown + Tagescap")

    # ── Booster ×1.5 ────────────────────────────────────────────
    await _reset(pool)
    assert await faucets.award_message(B, is_booster=True) == 3   # 2 * 1.5
    ok.append("Booster-Multiplikator 1,5×")

    # ── /gunst nur 1×/Tag ──────────────────────────────────────
    await _reset(pool)
    assert await faucets.claim_daily(A) == 50
    try:
        await faucets.claim_daily(A)
        raise AssertionError("zweites claim_daily hätte werfen müssen")
    except AlreadyClaimed:
        pass
    ok.append("/gunst 1×/Tag")

    # ── veil-Faucet nur verifiziert ────────────────────────────
    assert await faucets.award_veil(A, is_verified=False) == 0
    assert await faucets.award_veil(A, is_verified=True) == 1
    ok.append("Siegel-Faucet nur verifiziert")

    # ── shop: atomarer Kauf, Rollback bei Effekt-Fehler ────────
    await _reset(pool)
    await wallets.admin_set(A, "dukaten", 500)
    # erfolgreicher Kauf
    async with shop.purchase(A, "illuster", role_id=999) as rc:
        assert rc.item["cost"]["dukaten"] == 400
    assert (await wallets.balance(A))["dukaten"] == 100
    assert len(await shop.my_timed_roles(A)) == 1
    # Kauf mit Effekt-Fehler → nichts abgebucht
    await wallets.admin_set(A, "dukaten", 500)
    try:
        async with shop.purchase(A, "illuster", role_id=999):
            raise RuntimeError("Discord-Effekt schlug fehl")
    except RuntimeError:
        pass
    assert (await wallets.balance(A))["dukaten"] == 500, "Rollback bei Effekt-Fehler"
    ok.append("shop atomar + Rollback")

    # ── Mischpreis prüft beide Währungen ──────────────────────
    await _reset(pool)
    await wallets.admin_set(A, "dukaten", 500)
    await wallets.admin_set(A, "siegel", 30)   # zu wenig Siegel (braucht 50)
    try:
        async with shop.purchase(A, "prestige", role_id=1):
            pass
        raise AssertionError("Mischpreis-Kauf hätte scheitern müssen")
    except InsufficientFunds:
        pass
    assert (await wallets.balance(A))["dukaten"] == 500, "Dukaten dürfen nicht weg sein"
    ok.append("Mischpreis atomar (beide Währungen)")

    # ── timed roles: Ablauf ──────────────────────────────────
    await _reset(pool)
    await roles.grant(A, 42, "illuster", "haus", days=7)
    await pool.execute("UPDATE timed_roles SET expires_at = now() - interval '1 min' WHERE user_id=$1", A)
    d = await roles.due()
    assert len(d) == 1 and d[0]["role_id"] == 42
    await roles.mark_removed([d[0]["id"]])
    assert await roles.due() == []
    ok.append("Zeit-Rollen-Ablauf")

    # ── spotlight: Round-Robin nur online ────────────────────
    await _reset(pool)
    await spotlight.ensure_state("haus", 777)
    r1 = await spotlight.rotate("haus", [10, 20, 30])
    assert r1.add_to == 10 and r1.remove_from is None
    r2 = await spotlight.rotate("haus", [10, 20, 30])
    assert r2.remove_from == 10 and r2.add_to == 20
    r3 = await spotlight.rotate("haus", [10, 30])   # 20 offline
    assert r3.add_to == 30, r3
    r4 = await spotlight.rotate("haus", [])          # niemand online
    assert r4.remove_from == 30 and r4.add_to is None
    ok.append("spotlight Round-Robin + offline überspringen")

    # ── booster stipend: keine Doppelgutschrift ──────────────
    await _reset(pool)
    assert await boosters.grant_monthly(A) == 30
    assert await boosters.grant_monthly(A) == 0
    ok.append("Stipendium neustart-sicher")

    # ── markers: einmalig ───────────────────────────────────
    assert await markers.award(A, "gruendungsbewohner") is True
    assert await markers.award(A, "gruendungsbewohner") is False
    ok.append("Marker UNIQUE")

    # ── config runtime override ─────────────────────────────
    assert await config.get("msg_dukaten") == 2
    await config.set_value("msg_dukaten", 5)
    config._cache.at = 0.0
    assert await config.get("msg_dukaten") == 5
    ok.append("config DB-Override")

    await db.close()
    print("\n".join(f"  [ok] {x}" for x in ok))
    print(f"\n{len(ok)} Checks OK")


if __name__ == "__main__":
    asyncio.run(run())
