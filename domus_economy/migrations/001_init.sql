-- domus_economy — Schema (aus docs/waehrungssystem.md).
-- Idempotent: CREATE TABLE IF NOT EXISTS. Von db.run_migrations() beim Start ausgeführt.

CREATE TABLE IF NOT EXISTS wallets (
    user_id     BIGINT PRIMARY KEY,
    dukaten     BIGINT NOT NULL DEFAULT 0 CHECK (dukaten >= 0),
    siegel      BIGINT NOT NULL DEFAULT 0 CHECK (siegel  >= 0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS transactions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL,
    currency        TEXT   NOT NULL CHECK (currency IN ('dukaten','siegel')),
    amount          BIGINT NOT NULL,          -- + Gutschrift, − Abbuchung
    reason          TEXT   NOT NULL,
    counterparty_id BIGINT,
    meta            JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS transactions_user ON transactions (user_id, created_at);

CREATE TABLE IF NOT EXISTS timed_roles (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    role_id     BIGINT NOT NULL,
    tier        TEXT   NOT NULL,              -- 'illuster','schleier_rang','icon',…
    scope       TEXT   NOT NULL CHECK (scope IN ('haus','schleier')),
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    active      BOOLEAN NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS timed_roles_expiry ON timed_roles (expires_at) WHERE active;
CREATE INDEX IF NOT EXISTS timed_roles_user   ON timed_roles (user_id) WHERE active;

CREATE TABLE IF NOT EXISTS spotlight_state (
    scope             TEXT PRIMARY KEY CHECK (scope IN ('haus','schleier')),
    spotlight_role_id BIGINT NOT NULL,
    current_holder    BIGINT,
    last_holder       BIGINT,
    last_rotated_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS earn_cooldowns (
    user_id  BIGINT NOT NULL,
    faucet   TEXT   NOT NULL,                 -- 'daily','message','voice','veil'
    last_at  TIMESTAMPTZ NOT NULL,
    day      DATE,                            -- für Tages-Caps
    day_sum  BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, faucet)
);

CREATE TABLE IF NOT EXISTS booster_stipend (
    user_id      BIGINT PRIMARY KEY,
    last_granted DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS markers (
    id        BIGSERIAL PRIMARY KEY,
    user_id   BIGINT NOT NULL,
    marker    TEXT   NOT NULL,
    earned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, marker)
);

CREATE TABLE IF NOT EXISTS marker_progress (
    user_id  BIGINT NOT NULL,
    metric   TEXT   NOT NULL,                 -- 'ehrenplatz_haus','ehrenplatz_schleier'
    n        BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, metric)
);

CREATE TABLE IF NOT EXISTS economy_config (
    key   TEXT PRIMARY KEY,
    value JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS peer_gifts (
    user_id  BIGINT NOT NULL,
    day      DATE   NOT NULL,
    given    BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);
