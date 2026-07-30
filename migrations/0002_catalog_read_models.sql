CREATE TABLE IF NOT EXISTS catalog_games (
    game_id       TEXT PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT '',
    developer_id  TEXT NOT NULL DEFAULT '',
    published     BOOLEAN NOT NULL DEFAULT false,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS catalog_games_published_idx ON catalog_games (published);


CREATE TABLE IF NOT EXISTS promotion_snapshots (
    promotion_id              TEXT PRIMARY KEY,
    festival_id                TEXT NOT NULL,
    game_id                     TEXT NOT NULL,
    state                       TEXT NOT NULL,
    discount_bps                INTEGER NOT NULL DEFAULT 0,
    starts_at                   TIMESTAMPTZ NOT NULL,
    ends_at                     TIMESTAMPTZ NOT NULL,
    list_price_minor            BIGINT,
    list_price_currency         TEXT,
    effective_price_minor       BIGINT,
    effective_price_currency    TEXT,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS promotion_snapshots_festival_idx ON promotion_snapshots (festival_id);
CREATE INDEX IF NOT EXISTS promotion_snapshots_game_idx ON promotion_snapshots (game_id);
