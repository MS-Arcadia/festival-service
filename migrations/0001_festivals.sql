CREATE TABLE IF NOT EXISTS festivals (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    state        TEXT NOT NULL,
    starts_at    TIMESTAMPTZ NOT NULL,
    ends_at      TIMESTAMPTZ NOT NULL,
    created_by   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at   TIMESTAMPTZ,
    ended_at     TIMESTAMPTZ,
    version      INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT festivals_window_ck CHECK (ends_at > starts_at)
);

CREATE INDEX IF NOT EXISTS festivals_state_idx ON festivals (state);
CREATE INDEX IF NOT EXISTS festivals_starts_at_idx ON festivals (starts_at DESC);

CREATE TABLE IF NOT EXISTS festival_games (
    festival_id   TEXT NOT NULL REFERENCES festivals (id) ON DELETE CASCADE,
    game_id       TEXT NOT NULL,
    title         TEXT NOT NULL,
    developer_id  TEXT NOT NULL,
    added_by      TEXT NOT NULL,
    added_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (festival_id, game_id)
);

CREATE INDEX IF NOT EXISTS festival_games_game_id_idx ON festival_games (game_id);
