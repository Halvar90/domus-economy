CREATE TABLE IF NOT EXISTS economy_migrations (
    name       TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    PERFORM pg_advisory_xact_lock(704219843001);

    IF NOT EXISTS (
        SELECT 1 FROM economy_migrations WHERE name = '002_single_currency'
    ) THEN
        INSERT INTO transactions (user_id, currency, amount, reason, meta)
        SELECT user_id, 'dukaten', siegel, 'currency_consolidation',
               jsonb_build_object('from', 'siegel', 'rate', 1,
                                  'migration', '002_single_currency')
        FROM wallets
        WHERE siegel > 0;

        UPDATE wallets
        SET dukaten = dukaten + siegel,
            siegel = 0,
            updated_at = now()
        WHERE siegel > 0;

        DELETE FROM economy_config
        WHERE key IN ('veil_siegel', 'siegel_stipend', 'exchange_siegel_to_dukaten');

        INSERT INTO economy_migrations (name)
        VALUES ('002_single_currency');
    END IF;
END $$;
