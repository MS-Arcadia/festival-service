from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

SECRET = "test-only-jwt-secret-at-least-32-characters-long"


@pytest.fixture(scope="module")
def client():
    os.environ.update(
        {
            "DATABASE_URL": "postgresql://unused:unused@localhost:5432/unused",
            "JWT_SECRET": SECRET,
            "KAFKA_ENABLED": "false",
            "RUN_MIGRATIONS": "false",
            "ENVIRONMENT": "local",
            "LOG_JSON": "false",
        }
    )
    from app.bootstrap import build
    from app.config import get_config

    get_config.cache_clear()
    app = build()
    # No lifespan: it would run migrations and connect to Postgres, and nothing
    # these tests assert on gets that far.
    return TestClient(app, raise_server_exceptions=False)


def token(*, role: str = "BASIC_USER", user_id: str = "user-1", typ: str = "access", **extra):
    claims = {
        "sub": user_id,
        "role": role,
        "typ": typ,
        "iss": "arcadia-auth",
        "aud": "arcadia",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        **extra,
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


def auth(**kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(**kwargs)}"}


# --- liveness is not behind auth -----------------------------------------


def test_liveness_needs_no_token(client):
    response = client.get("/livez")
    assert response.status_code == 200
    assert response.json()["status"] == "UP"


# --- browsing is public, matching the catalogue's own precedent ---------


def test_listing_festivals_needs_no_token(client):
    response = client.get("/v1/festivals")
    assert response.status_code != 401


def test_getting_a_festival_needs_no_token(client):
    response = client.get("/v1/festivals/fest-1")
    assert response.status_code != 401


# --- authentication -------------------------------------------------------


def test_creating_a_festival_without_a_token_is_rejected(client):
    response = client.post(
        "/v1/festivals",
        json={
            "name": "Summer Sale",
            "starts_at": "2027-01-01T00:00:00Z",
            "ends_at": "2027-01-08T00:00:00Z",
        },
    )
    assert response.status_code == 401
    assert response.json()["reason"] == "TOKEN_MISSING"


def test_the_error_is_an_rfc_7807_problem_document(client):
    response = client.post("/v1/festivals", json={"name": "x"})
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 401
    assert "title" in body and "detail" in body


def test_a_refresh_token_is_not_a_credential(client):
    response = client.post(
        "/v1/festivals",
        json={"name": "x", "starts_at": "2027-01-01T00:00:00Z", "ends_at": "2027-01-08T00:00:00Z"},
        headers=auth(role="ADMIN", typ="refresh"),
    )
    assert response.status_code == 401
    assert response.json()["reason"] == "REFRESH_TOKEN_USED"


# --- role checks: requirement 1.9 gives this to Admin, and only Admin ---


def test_a_basic_user_cannot_create_a_festival(client):
    response = client.post(
        "/v1/festivals",
        json={"name": "x", "starts_at": "2027-01-01T00:00:00Z", "ends_at": "2027-01-08T00:00:00Z"},
        headers=auth(role="BASIC_USER"),
    )
    assert response.status_code == 403
    assert response.json()["reason"] == "ROLE_REQUIRED"


def test_support_cannot_create_a_festival(client):
    """Requirement 1.9 names the platform (Admin) as the one who runs a
    festival — Support's role in this story is deciding a discount inside
    Catalog, not standing up the festival itself."""
    response = client.post(
        "/v1/festivals",
        json={"name": "x", "starts_at": "2027-01-01T00:00:00Z", "ends_at": "2027-01-08T00:00:00Z"},
        headers=auth(role="SUPPORT"),
    )
    assert response.status_code == 403


def test_a_developer_cannot_start_a_festival(client):
    response = client.post("/v1/festivals/fest-1/start", headers=auth(role="DEVELOPER"))
    assert response.status_code == 403


def test_a_basic_user_cannot_add_a_game_to_a_festival(client):
    response = client.post(
        "/v1/festivals/fest-1/games", json={"game_id": "game-1"}, headers=auth(role="BASIC_USER")
    )
    assert response.status_code == 403


# --- request validation -------------------------------------------------


def test_an_unknown_field_is_rejected_rather_than_ignored(client):
    response = client.post(
        "/v1/festivals",
        json={
            "name": "x",
            "starts_at": "2027-01-01T00:00:00Z",
            "ends_at": "2027-01-08T00:00:00Z",
            "titel": "typo",
        },
        headers=auth(role="ADMIN"),
    )
    assert response.status_code == 400
    assert response.json()["reason"] == "VALIDATION_FAILED"


def test_an_oversized_page_is_rejected(client):
    """The page cap is a denial-of-service guard, so it is enforced, not
    clamped."""
    response = client.get("/v1/festivals?limit=100000")
    assert response.status_code == 400
