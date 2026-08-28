from __future__ import annotations

import random
import secrets
from typing import Annotated, Any

from fastapi import FastAPI, Header, status

from ai import make_bot
from engine import (
    Action,
    InvalidAction,
    Outcome,
    PlayerId,
    RunSilent,
    resign,
    resolve,
    validate_action,
)
from perception import to_payload, view_for
from server.errors import ApiError, register_error_handlers
from server.schemas import (
    ActionRequest,
    ActionResponse,
    CreateRequest,
    SeatResponse,
    history_payload,
    to_action,
)
from server.store import MatchRecord, MatchStore, RoundRecord

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


def _phase(record: MatchRecord, player: PlayerId) -> str:
    if record.state.last_events is not None and player not in record.pending:
        return "RESOLVED"
    return "AWAITING_ACTIONS"


def _view(record: MatchRecord, player: PlayerId) -> dict[str, Any]:
    return to_payload(
        view_for(
            record.state,
            player,
            record.view_rng(player),
            phase=_phase(record, player),
        )
    )


def _bot_action(record: MatchRecord) -> Action:
    """Ask the seated bot for its move, from the same fogged view a human gets.

    Built from the state *before* the human's action is applied, so the bot is
    choosing blind against a simultaneous opponent exactly as the rules intend.

    An illegal answer is replaced with Run Silent rather than failing the
    human's request: it is the same safe default a player gets for missing a
    turn, and the alternative is a bot bug reading as a 400 on someone else's
    perfectly good action.
    """
    view = view_for(
        record.state,
        PlayerId.P2,
        record.view_rng(PlayerId.P2),
        phase="AWAITING_ACTIONS",
    )
    action = record.opponent.choose_action(view)  # type: ignore[union-attr]
    try:
        validate_action(action, record.state.config)
    except InvalidAction:
        return RunSilent()
    return action


def _resolve_round(record: MatchRecord) -> None:
    actions = dict(record.pending)
    new_state, events = resolve(
        record.state,
        actions[PlayerId.P1],
        actions[PlayerId.P2],
        record.resolve_rng(),
    )
    record.history.append(
        RoundRecord(
            round=events.round,
            actions=actions,
            events=events,
            ships_after=dict(new_state.ships),
        )
    )
    record.state = new_state
    record.pending.clear()


@app.post("/matches", status_code=status.HTTP_201_CREATED)
def create_match(body: CreateRequest | None = None) -> SeatResponse:
    """Create a match, against a friend by code or against a bot straight away."""
    request = body or CreateRequest()
    opponent = None
    if request.opponent == "ai":
        opponent = make_bot(request.level, random.Random(secrets.randbits(64)))

    record, token = store.create(opponent=opponent)
    return SeatResponse(
        match_id=record.match_id,
        player_id=PlayerId.P1.value,
        token=token,
        view=_view(record, PlayerId.P1),
        opponent="human" if opponent is None else opponent.name,
    )


@app.post("/matches/{match_id}/join")
def join_match(match_id: str) -> SeatResponse:
    """Take the second seat by join code."""
    record = _match(match_id)
    if record.is_full:
        raise ApiError(409, "match_full", "this match already has two players")

    token = record.seat(PlayerId.P2)
    return SeatResponse(
        match_id=record.match_id,
        player_id=PlayerId.P2.value,
        token=token,
        view=_view(record, PlayerId.P2),
    )


@app.get("/matches/{match_id}/view")
def get_view(match_id: str, authorization: AuthHeader = None) -> dict[str, Any]:
    """The caller's fogged view. The token alone decides which player is asking."""
    record = _match(match_id)
    return _view(record, _player(record, authorization))


@app.post("/matches/{match_id}/action")
def submit_action(
    match_id: str, body: ActionRequest, authorization: AuthHeader = None
) -> ActionResponse:
    """Submit one action. The round resolves only once both players have acted."""
    record = _match(match_id)
    player = _player(record, authorization)

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

    if record.opponent is not None and PlayerId.P2 not in record.pending:
        record.pending[PlayerId.P2] = _bot_action(record)

    if len(record.pending) == 2:
        _resolve_round(record)
        return ActionResponse(round=record.state.round, phase="RESOLVED")
    return ActionResponse(round=record.state.round, phase="AWAITING_ACTIONS")


@app.post("/matches/{match_id}/resign")
def resign_match(match_id: str, authorization: AuthHeader = None) -> dict[str, Any]:
    """Resign; the opponent wins."""
    record = _match(match_id)
    player = _player(record, authorization)

    if record.state.outcome is not Outcome.ONGOING:
        raise ApiError(409, "match_over", "this match has already ended")

    record.state = resign(record.state, player)
    record.pending.clear()
    return _view(record, player)


@app.get("/matches/{match_id}/history")
def get_history(match_id: str, authorization: AuthHeader = None) -> dict[str, Any]:
    """The de-fogged record of both ships, available only once the match has ended."""
    record = _match(match_id)
    _player(record, authorization)

    # The one endpoint that returns both ships' true tracks. It is safe only
    # because the match is over, so this guard is the load-bearing line here.
    if record.state.outcome is Outcome.ONGOING:
        raise ApiError(
            409,
            "match_in_progress",
            "the full record is available only once the match has ended",
        )
    return history_payload(record)
