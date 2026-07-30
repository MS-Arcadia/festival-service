# festival-service

Platform-run sales.

## What this service owns, and what it doesn't

The first three bullets are this service: an Admin creates a festival, selects
the games in it, and runs it through **DRAFT → ACTIVE → ENDED** (or
**CANCELLED**).

The fourth bullet — a discount, proposed by Support and approved by the
developer — is **not** implemented here. It already exists in `catalog-service`
as the `Promotion` aggregate, which carries an opaque `festival_id` for exactly
this purpose. Rebuilding that approval workflow a second time in this service
would produce two answers to "is this game discounted" whenever they disagreed.
Instead, this service:

1. Consumes Catalog's `game-events` to keep a small local read-model of which
   games exist, are published, and what Catalog has decided about their
   promotions.
2. Publishes `arcadia.festival.v1.DiscountApplied` the moment it sees a
   `PromotionApproved` for a game it has selected into one of its festivals —
   the moment the price actually changes for a buyer.

This split was found by reading the already-built `catalog-service` and
`notification-service` repositories rather than guessing:

- `catalog-service`'s `app/domain/promotion.py` and
  `app/adapters/inbound/rest/workflow.py` implement the propose → approve/reject
  → cancel workflow, keyed by `festival_id`.
- `notification-service`'s `app/domain/translation.py` already has a translator
  registered for `arcadia.festival.v1.FestivalStarted`, waiting for this
  service to exist. Its expected payload shape (`name`, `festival_id`,
  `audience`) is what `FestivalService.start` publishes.

## Architecture

Same shape as every other Python service on the platform: Clean Architecture
per service (`domain` → `application` → `adapters`), a transactional outbox for
at-least-once delivery to Kafka, JWT/RBAC at the edge, and RFC 7807 problem
documents for errors. The `app/platform` package is vendored, not shared code —
each service on this platform keeps its own copy so one service's change to it
can't silently move another service's ground under it.

```
app/
  domain/
    festival.py        Festival aggregate: creation, game selection, lifecycle
    catalog_sync.py     Read-model value objects fed by game-events
  application/
    ports.py            Repository/publisher protocols
    events.py            Published and consumed event type names
    dto.py                Request/response shapes
    festival_service.py    Admin use cases (create, select games, lifecycle)
    catalog_sync_service.py  Consumer-driven read-model updates + DiscountApplied
  adapters/
    inbound/
      rest/festivals.py    /v1/festivals — public browsing, Admin-only writes
      consumer.py           Kafka handlers for game-events
    outbound/
      models.py             SQLAlchemy tables
      repositories.py        Postgres repositories
      publisher.py            Outbox-backed event publisher
  bootstrap.py            Wires everything together
  config.py               Settings
  main.py                  ASGI entrypoint
migrations/                festivals, the read-models, the outbox
tests/                      Domain, application, and HTTP-authorisation tests
                             against in-memory fakes — no database needed
```

## Events

Published on `festival-events`:

| Event | When |
|---|---|
| `FestivalCreated` | Admin creates a festival |
| `FestivalGameAdded` / `FestivalGameRemoved` | Admin edits the game list |
| `FestivalStarted` | Admin opens the festival (requires at least one game) |
| `FestivalEnded` | Admin closes a running festival |
| `FestivalCancelled` | Admin calls off a DRAFT or ACTIVE festival |
| `DiscountApplied` | Catalog approves a promotion for a selected game |

Consumed from `game-events` (produced by `catalog-service`):
`GamePublished`, `GameWithdrawn`, `GameRelisted`, `GameUpdated` (the game
read-model), and `PromotionProposed` / `PromotionApproved` / `PromotionRejected`
/ `PromotionCancelled` (the promotion read-model, and the `DiscountApplied`
trigger). `dead_letter_unknown` is off for this router — `game-events` is a
shared topic and most of its traffic (`GameSubmitted`, `GameApproved`, …) is
none of this service's business.

### The `audience` field on `FestivalStarted`

Notification's translator reads an `audience` field — a list of user ids to
notify. This service has no user directory (that would mean calling Auth or
Profile synchronously for every user on the platform on every festival start),
so it is published as an empty list. This is a deliberate, documented gap: a
future targeted-marketing feature can populate it without a schema change on
either side.

## Running it

```
make install   # venv + dependencies
make test      # the full suite — no database or broker needed
make lint      # ruff check + format check
make run       # against the infra compose stack, on :8091
make docker    # build the image
```
