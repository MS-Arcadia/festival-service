from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.festival import Festival, FestivalState
from app.platform import errors

NOW = datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)


def make_festival(**overrides) -> Festival:
    defaults = {
        "festival_id": "fest-1",
        "name": "Summer Sale",
        "description": "",
        "starts_at": NOW + timedelta(days=1),
        "ends_at": NOW + timedelta(days=8),
        "created_by": "admin-1",
        "now": NOW,
    }
    defaults.update(overrides)
    return Festival.create(**defaults)


def test_a_new_festival_is_a_draft():
    festival = make_festival()
    assert festival.state is FestivalState.DRAFT
    assert festival.games == {}


def test_a_festival_needs_a_name():
    with pytest.raises(errors.AppError) as exc:
        make_festival(name="   ")
    assert exc.value.reason == "FESTIVAL_NAME_REQUIRED"


def test_a_festival_must_end_after_it_starts():
    with pytest.raises(errors.AppError) as exc:
        make_festival(starts_at=NOW + timedelta(days=8), ends_at=NOW + timedelta(days=1))
    assert exc.value.reason == "FESTIVAL_WINDOW_INVALID"


def test_a_festival_cannot_end_in_the_past():
    with pytest.raises(errors.AppError) as exc:
        make_festival(starts_at=NOW - timedelta(days=10), ends_at=NOW - timedelta(days=1))
    assert exc.value.reason == "FESTIVAL_WINDOW_INVALID"


# --- selecting games ------------------------------------------------------


def test_admin_can_add_a_game():
    festival = make_festival()
    festival.add_game(
        game_id="game-1", title="Star Fox", developer_id="dev-1", added_by="admin-1", now=NOW
    )
    assert "game-1" in festival.games
    assert festival.games["game-1"].title == "Star Fox"


def test_the_same_game_cannot_be_added_twice():
    festival = make_festival()
    festival.add_game(
        game_id="game-1", title="Star Fox", developer_id="dev-1", added_by="admin-1", now=NOW
    )
    with pytest.raises(errors.AppError) as exc:
        festival.add_game(
            game_id="game-1", title="Star Fox", developer_id="dev-1", added_by="admin-1", now=NOW
        )
    assert exc.value.reason == "GAME_ALREADY_IN_FESTIVAL"


def test_removing_a_game_not_selected_is_rejected():
    festival = make_festival()
    with pytest.raises(errors.AppError) as exc:
        festival.remove_game(game_id="ghost")
    assert exc.value.reason == "GAME_NOT_IN_FESTIVAL"


def test_games_cannot_be_edited_once_the_festival_has_ended():
    festival = make_festival()
    festival.add_game(
        game_id="game-1", title="Star Fox", developer_id="dev-1", added_by="admin-1", now=NOW
    )
    festival.start(now=NOW)
    festival.end(now=NOW + timedelta(days=9))
    with pytest.raises(errors.AppError) as exc:
        festival.add_game(
            game_id="game-2",
            title="Chrono Trigger",
            developer_id="dev-2",
            added_by="admin-1",
            now=NOW,
        )
    assert exc.value.reason == "FESTIVAL_WRONG_STATE"


# --- lifecycle -------------------------------------------------------------


def test_a_festival_with_no_games_cannot_start():
    festival = make_festival()
    with pytest.raises(errors.AppError) as exc:
        festival.start(now=NOW)
    assert exc.value.reason == "FESTIVAL_HAS_NO_GAMES"


def test_starting_moves_draft_to_active():
    festival = make_festival()
    festival.add_game(
        game_id="game-1", title="Star Fox", developer_id="dev-1", added_by="admin-1", now=NOW
    )
    festival.start(now=NOW)
    assert festival.state is FestivalState.ACTIVE
    assert festival.started_at == NOW


def test_an_already_active_festival_cannot_be_started_again():
    festival = make_festival()
    festival.add_game(
        game_id="game-1", title="Star Fox", developer_id="dev-1", added_by="admin-1", now=NOW
    )
    festival.start(now=NOW)
    with pytest.raises(errors.AppError) as exc:
        festival.start(now=NOW)
    assert exc.value.reason == "FESTIVAL_WRONG_STATE"


def test_only_an_active_festival_can_end():
    festival = make_festival()
    with pytest.raises(errors.AppError) as exc:
        festival.end(now=NOW)
    assert exc.value.reason == "FESTIVAL_WRONG_STATE"


def test_a_draft_festival_can_be_cancelled():
    festival = make_festival()
    festival.cancel(now=NOW)
    assert festival.state is FestivalState.CANCELLED


def test_an_ended_festival_cannot_be_cancelled():
    festival = make_festival()
    festival.add_game(
        game_id="game-1", title="Star Fox", developer_id="dev-1", added_by="admin-1", now=NOW
    )
    festival.start(now=NOW)
    festival.end(now=NOW + timedelta(days=9))
    with pytest.raises(errors.AppError) as exc:
        festival.cancel(now=NOW)
    assert exc.value.reason == "FESTIVAL_WRONG_STATE"


def test_rescheduling_is_only_allowed_before_it_starts():
    festival = make_festival()
    festival.add_game(
        game_id="game-1", title="Star Fox", developer_id="dev-1", added_by="admin-1", now=NOW
    )
    festival.start(now=NOW)
    with pytest.raises(errors.AppError) as exc:
        festival.reschedule(starts_at=NOW, ends_at=NOW + timedelta(days=20), now=NOW)
    assert exc.value.reason == "FESTIVAL_WRONG_STATE"
