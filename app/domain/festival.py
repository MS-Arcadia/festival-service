from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.platform import errors

NAME_MAX = 200
DESCRIPTION_MAX = 4_000

REASON_WRONG_STATE = "FESTIVAL_WRONG_STATE"
REASON_BAD_WINDOW = "FESTIVAL_WINDOW_INVALID"
REASON_NAME_REQUIRED = "FESTIVAL_NAME_REQUIRED"
REASON_GAME_ALREADY_SELECTED = "GAME_ALREADY_IN_FESTIVAL"
REASON_GAME_NOT_SELECTED = "GAME_NOT_IN_FESTIVAL"
REASON_NO_GAMES = "FESTIVAL_HAS_NO_GAMES"


class FestivalState(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"



_EDITABLE = frozenset({FestivalState.DRAFT, FestivalState.ACTIVE})


@dataclass(slots=True)
class FestivalGame:
    """One game selected into a festival.

    ``title`` and ``developer_id`` are copied in at selection time from this
    service's own read-model of the catalog (see ``catalog_sync``), so a festival
    page renders without calling another service for every game in it. They are a
    snapshot, not a live join — if a developer renames a game afterwards, the
    festival keeps showing the name it had when it was picked, exactly as an order
    keeps the price it was placed at.
    """

    game_id: str
    title: str
    developer_id: str
    added_by: str
    added_at: datetime


@dataclass(slots=True)
class Festival:
    """A themed sale the platform runs over a fixed window."""

    id: str
    name: str
    description: str
    starts_at: datetime
    ends_at: datetime
    state: FestivalState
    created_by: str
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    games: dict[str, FestivalGame] = field(default_factory=dict)
    version: int = 0


    @classmethod
    def create(
        cls,
        *,
        festival_id: str,
        name: str,
        description: str,
        starts_at: datetime,
        ends_at: datetime,
        created_by: str,
        now: datetime,
    ) -> Festival:
        name = name.strip()
        if not name:
            raise errors.invalid_argument("a festival needs a name", reason=REASON_NAME_REQUIRED)
        if len(name) > NAME_MAX:
            raise errors.invalid_argument(
                f"a festival name is at most {NAME_MAX} characters", reason=REASON_NAME_REQUIRED
            )
        _check_window(starts_at, ends_at, now)

        return cls(
            id=festival_id,
            name=name,
            description=description.strip()[:DESCRIPTION_MAX],
            starts_at=starts_at,
            ends_at=ends_at,
            state=FestivalState.DRAFT,
            created_by=created_by,
            created_at=now,
        )


    def reschedule(self, *, starts_at: datetime, ends_at: datetime, now: datetime) -> None:
        """Change the window. Only while nothing has actually started.

        Moving the goalposts on a festival that is already running would make
        ``FestivalStarted`` a lie about when it happened.
        """
        if self.state is not FestivalState.DRAFT:
            raise errors.conflict(
                f"cannot reschedule a festival that is {self.state}",
                reason=REASON_WRONG_STATE,
                state=str(self.state),
            )
        _check_window(starts_at, ends_at, now)
        self.starts_at = starts_at
        self.ends_at = ends_at

    def add_game(
        self, *, game_id: str, title: str, developer_id: str, added_by: str, now: datetime
    ) -> None:
        self._require_editable("add a game to")
        if game_id in self.games:
            raise errors.already_exists(
                f"game {game_id} is already in this festival", reason=REASON_GAME_ALREADY_SELECTED
            )
        self.games[game_id] = FestivalGame(
            game_id=game_id,
            title=title,
            developer_id=developer_id,
            added_by=added_by,
            added_at=now,
        )

    def remove_game(self, *, game_id: str) -> None:
        self._require_editable("remove a game from")
        if game_id not in self.games:
            raise errors.not_found(
                f"game {game_id} is not in this festival", reason=REASON_GAME_NOT_SELECTED
            )
        del self.games[game_id]


    def start(self, *, now: datetime) -> None:
        """Open the festival. Requirement 1.9's admin action, and what
        ``FestivalStarted`` reports."""
        if self.state is not FestivalState.DRAFT:
            raise errors.conflict(
                f"cannot start a festival that is {self.state}",
                reason=REASON_WRONG_STATE,
                state=str(self.state),
            )
        if not self.games:
            raise errors.failed_precondition(
                "a festival needs at least one selected game before it can start",
                reason=REASON_NO_GAMES,
            )
        self.state = FestivalState.ACTIVE
        self.started_at = now

    def end(self, *, now: datetime) -> None:
        """Close the festival, whether the window ran out or an operator cut it short."""
        if self.state is not FestivalState.ACTIVE:
            raise errors.conflict(
                f"cannot end a festival that is {self.state}",
                reason=REASON_WRONG_STATE,
                state=str(self.state),
            )
        self.state = FestivalState.ENDED
        self.ended_at = now

    def cancel(self, *, now: datetime) -> None:
        """Call the whole thing off before or during the run — never after."""
        if self.state not in (FestivalState.DRAFT, FestivalState.ACTIVE):
            raise errors.conflict(
                f"cannot cancel a festival that is {self.state}",
                reason=REASON_WRONG_STATE,
                state=str(self.state),
            )
        self.state = FestivalState.CANCELLED
        self.ended_at = now


    def _require_editable(self, action: str) -> None:
        if self.state not in _EDITABLE:
            raise errors.conflict(
                f"cannot {action} a festival that is {self.state}",
                reason=REASON_WRONG_STATE,
                state=str(self.state),
            )


def _check_window(starts_at: datetime, ends_at: datetime, now: datetime) -> None:
    if ends_at <= starts_at:
        raise errors.invalid_argument(
            "a festival must end after it starts", reason=REASON_BAD_WINDOW
        )
    if ends_at <= now:
        raise errors.invalid_argument("a festival cannot end in the past", reason=REASON_BAD_WINDOW)
