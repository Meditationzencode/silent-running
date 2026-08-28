from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from engine import Action, Fire, Move, Ping, PlayerId, RunSilent, ShipState
from server.errors import ApiError
from server.store import MatchRecord


class CreateRequest(BaseModel):
    opponent: Literal["human", "ai"] = "human"
    level: int = Field(default=3, ge=1, le=5)


class ActionRequest(BaseModel):
    type: Literal["MOVE", "FIRE", "PING", "RUN_SILENT"]
    direction: str | None = None
    target: tuple[int, int] | None = None


class SeatResponse(BaseModel):
    match_id: str
    player_id: str
    token: str
    view: dict[str, Any]
    opponent: str = "human"


class ActionResponse(BaseModel):
    round: int
    phase: Literal["AWAITING_ACTIONS", "RESOLVED"]


def to_action(request: ActionRequest) -> Action:
    """Translate a request body into an engine Action. Legality is engine's call."""
    if request.type == "RUN_SILENT":
        return RunSilent()
    if request.type == "PING":
        return Ping()
    if request.type == "MOVE":
        if request.direction is None:
            raise ApiError(400, "direction_required", "a MOVE needs a direction")
        return Move(request.direction)
    if request.target is None:
        raise ApiError(400, "target_required", "a FIRE needs a target cell")
    return Fire((request.target[0], request.target[1]))


def action_payload(action: Action) -> dict[str, Any]:
    if isinstance(action, Move):
        return {"type": "MOVE", "direction": action.direction}
    if isinstance(action, Fire):
        return {"type": "FIRE", "target": list(action.target)}
    if isinstance(action, Ping):
        return {"type": "PING"}
    return {"type": "RUN_SILENT"}


def ship_payload(ship: ShipState) -> dict[str, Any]:
    return {
        "position": list(ship.position),
        "hull": ship.hull,
        "alive": ship.alive,
    }


def history_payload(record: MatchRecord) -> dict[str, Any]:
    """The de-fogged record. Only ever reachable once the match has ended."""
    return {
        "match_id": record.match_id,
        "outcome": record.state.outcome.value,
        "rounds": [
            {
                "round": entry.round,
                "actions": {
                    player.value: action_payload(action)
                    for player, action in entry.actions.items()
                },
                "ships_after": {
                    player.value: ship_payload(ship)
                    for player, ship in entry.ships_after.items()
                },
                "emissions": [
                    {
                        "source": emission.source.value,
                        "kind": emission.kind,
                        "position": list(emission.position),
                    }
                    for emission in entry.events.emissions
                ],
                "detonations": [
                    {
                        "source": detonation.source.value,
                        "target": list(detonation.target),
                        "caught": [player.value for player in detonation.caught],
                    }
                    for detonation in entry.events.detonations
                ],
            }
            for entry in record.history
        ],
        "final_positions": {
            player.value: ship_payload(ship)
            for player, ship in record.state.ships.items()
        },
    }


PLAYER_IDS = tuple(player.value for player in PlayerId)
