CREATE TABLE IF NOT EXISTS outbox_messages (
    id            BIGSERIAL   PRIMARY KEY,
    event_id      TEXT        NOT NULL UNIQUE,
    event_type    TEXT        NOT NULL,
    topic         TEXT        NOT NULL,
    partition_key TEXT        NOT NULL,
    envelope      JSONB       NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at  TIMESTAMPTZ,
    attempts      INTEGER     NOT NULL DEFAULT 0,
    last_error    TEXT
);


CREATE INDEX IF NOT EXISTS ix_outbox_pending
    ON outbox_messages (id)
    WHERE published_at IS NULL;
