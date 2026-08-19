"""Action validation: the server refuses to enter an illegal state.

The client cannot construct an illegal state, because every action passes
through here before any mutation happens (PRD §3). Validation raises a domain
exception rather than returning an HTTP status: the engine stays pure and
transport-agnostic, and ``server`` maps ``InvalidAction`` to a 400 with the
structured body the PRD specifies.
"""

from __future__ import annotations

from config import DEFAULT, GameConfig
from engine.geometry import on_grid
from engine.models import DIRECTION_VECTORS, Action, Fire, Move, Ping, RunSilent


class InvalidAction(ValueError):
    """A structurally or domain-invalid action. The server renders this as 400.

    ``code`` is the machine-readable value for the PRD's error body
    ``{"error": ..., "detail": ...}``; ``detail`` is the human half.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def validate_action(action: Action, config: GameConfig = DEFAULT) -> None:
    """Raise ``InvalidAction`` if this action may not be submitted.

    Only two things can be wrong with an otherwise well-formed action: a Move
    naming a direction that does not exist, and a Fire naming a cell off the
    grid. Run Silent and Ping carry no parameters, so they are always legal.

    Note what is deliberately *not* validated: a Fire may target any on-grid
    cell, including the firer's own. Blind fire at a guessed cell is the central
    move of the game, so the engine must not second-guess the target.
    """
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
    """Structural guard for a Fire target.

    The server's request model should catch this first, but the engine is also
    called directly by tests and by the AI module, so it does not assume a
    well-behaved caller. ``bool`` is excluded because it is a subclass of ``int``
    and ``Fire((True, False))`` is a bug, not a cell.
    """
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    )
