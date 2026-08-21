from __future__ import annotations

from config import DEFAULT, GameConfig
from engine.geometry import on_grid
from engine.models import DIRECTION_VECTORS, Action, Fire, Move, Ping, RunSilent


class InvalidAction(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def validate_action(action: Action, config: GameConfig = DEFAULT) -> None:
    match action:
        case Move(direction=direction):
            if direction not in DIRECTION_VECTORS:
                raise InvalidAction(
                    "invalid_direction",
                    f"{direction!r} is not one of {sorted(DIRECTION_VECTORS)}",
                )
        case Fire(target=target):
            if not _is_cell(target):
                raise InvalidAction(
                    "target_out_of_bounds",
                    f"target {target!r} is not an (x, y) pair of integers",
                )
            if not on_grid(target, config):
                raise InvalidAction(
                    "target_out_of_bounds",
                    f"target ({target[0]},{target[1]}) is off-grid",
                )
        case RunSilent() | Ping():
            pass
        case _:
            raise InvalidAction(
                "invalid_action", f"{type(action).__name__} is not a known action"
            )


def _is_cell(value: object) -> bool:
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    )
