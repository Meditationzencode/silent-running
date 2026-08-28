from __future__ import annotations

import random
import secrets
from typing import Annotated, Any

from fastapi import FastAPI, Header, status

from ai import make_bot
from engine import Outcome, PlayerId, resign, validate_action
from perception import to_payload, view_for
from server.errors import ApiError, register_error_handlers
from server.participation import advance, status_of, touch
from server.rounds import fill_bot_seat, resolve_round
from server.schemas import (
    ActionRequest,
    ActionResponse,
    CreateRequest,
    SeatResponse,
    history_payload,
    to_action,
)
from server.store import MatchRecord, MatchStore

app = FastAPI(title="Silent Running", version="1.0.0")
store = MatchStore()
register_error_handlers(app)

AuthHeader = Annotated[str | None, Header(alias="Authorization")]


def _match(match_id: str) -> MatchRecord:
    record = store.get(match_id)
    if record is None:
        raise ApiError(404, "match_not_found", f"no match with id {match_id!r}")
    return record


def _player(record: MatchRecord, authorization: str | None) -> PlayerId:
    if authorization is None or not authorization.lower().startswith("bearer "):
        raise ApiError(
            401, "missing_token", "expected an 'Authorization: Bearer <token>' header"
        )

    player = record.player_for(authorization.split(" ", 1)[1].strip())
    if player is None:
        raise ApiError(403, "invalid_token", "that token does not belong to this match")
    return player


def _authenticated(
    match_id: str, authorization: str | None
) -> tuple[MatchRecord, PlayerId, float]:
    """Resolve the caller, run the clock forward, then record that they are here.

    Every authenticated route goes through this, which is what makes the
    timeout and abandonment rules work without a scheduler: the polling that
    keeps you visible is the same traffic that notices your opponent is gone.
    """
    record = _match(match_id)
    player = _player(record, authorization)
    now = store.clock()

    advance(record, now, record.state.config)
    touch(record, player, now)
    return record, player, now


def _phase(record: MatchRecord, player: PlayerId) -> str:
    if record.state.last_events is not None and player not in record.pending:
        return "RESOLVED"
    return "AWAITING_ACTIONS"


def _view(record: MatchRecord, player: PlayerId, now: float) -> dict[str, Any]:
    return to_payload(
        view_for(
            record.state,
            player,
            record.view_rng(player),
            phase=_phase(record, player),
            opponent_status=status_of(
                record, player.other, now, record.state.config
            ),
        )
    )


@app.post("/matches", status_code=status.HTTP_201_CREATED)
def create_match(body: CreateRequest | None = None) -> SeatResponse:
    """Create a match, against a friend by code or against a bot straight away."""
    request = body or CreateRequest()
    opponent = None
    if request.opponent == "ai":
        opponent = make_bot(request.level, random.Random(secrets.randbits(64)))

    record, token = store.create(opponent=opponent)
    now = store.clock()
    touch(record, PlayerId.P1, now)
    return SeatResponse(
        match_id=record.match_id,
        player_id=PlayerId.P1.value,
        token=token,
        view=_view(record, PlayerId.P1, now),
        opponent="human" if opponent is None else opponent.name,
    )


@app.post("/matches/{match_id}/join")
def join_match(match_id: str) -> SeatResponse:
    """Take the second seat by join code."""
    record = _match(match_id)
    if record.is_full:
        raise ApiError(409, "match_full", "this match already has two players")

    token = record.seat(PlayerId.P2)
    now = store.clock()
    touch(record, PlayerId.P2, now)
    # The clock on both the round and the grace window starts once there is
    # someone to be late for.
    record.round_opened_at = now
    return SeatResponse(
        match_id=record.match_id,
        player_id=PlayerId.P2.value,
        token=token,
        view=_view(record, PlayerId.P2, now),
    )


@app.get("/matches/{match_id}/view")
def get_view(match_id: str, authorization: AuthHeader = None) -> dict[str, Any]:
    """The caller's fogged view. The token alone decides which player is asking."""
    record, player, now = _authenticated(match_id, authorization)
    return _view(record, player, now)


@app.post("/matches/{match_id}/action")
def submit_action(
    match_id: str, body: ActionRequest, authorization: AuthHeader = None
) -> ActionResponse:
    """Submit one action. The round resolves only once both players have acted."""
    record, player, now = _authenticated(match_id, authorization)

    if record.state.outcome is not Outcome.ONGOING:
        raise ApiError(409, "match_over", "this match has already ended")
    if player in record.pending:
        raise ApiError(
            409,
            "already_acted",
            f"you have already submitted an action for round {record.state.round}",
        )

    action = to_action(body)
    validate_action(action, record.state.config)
    record.pending[player] = action
    record.timeouts[player] = 0

    fill_bot_seat(record)
    if len(record.pending) == 2:
        resolve_round(record, now)
        return ActionResponse(round=record.state.round, phase="RESOLVED")
    return ActionResponse(round=record.state.round, phase="AWAITING_ACTIONS")


@app.post("/matches/{match_id}/resign")
def resign_match(match_id: str, authorization: AuthHeader = None) -> dict[str, Any]:
    """Resign; the opponent wins."""
    record, player, now = _authenticated(match_id, authorization)

    if record.state.outcome is not Outcome.ONGOING:
        raise ApiError(409, "match_over", "this match has already ended")

    record.state = resign(record.state, player)
    record.pending.clear()
    return _view(record, player, now)


@app.get("/matches/{match_id}/history")
def get_history(match_id: str, authorization: AuthHeader = None) -> dict[str, Any]:
    """The de-fogged record of both ships, available only once the match has ended."""
    record, _, _ = _authenticated(match_id, authorization)

    # The one endpoint that returns both ships' true tracks. It is safe only
    # because the match is over, so this guard is the load-bearing line here.
    if record.state.outcome is Outcome.ONGOING:
        raise ApiError(
            409,
            "match_in_progress",
            "the full record is available only once the match has ended",
        )
    return history_payload(record)
