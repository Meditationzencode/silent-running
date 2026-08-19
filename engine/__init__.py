"""Game rules. Pure, deterministic, no I/O.

Contract for everything in this package:

* No network, no filesystem, no printing, no mutable module globals.
* Deterministic given a seeded ``rng``, so the same inputs always produce the
  same output and every rule is reproducible in a test.
* Holds 100% of the game rules — movement, emissions, detonation, win checking.
  ``server`` contains none of them.

The engine consumes and produces ``GameState``, the full truth. ``GameState`` is
never serialized into a response body; see ``perception`` for the only thing
that is.

The names re-exported below are the package's public surface. ``server``, tests
and ``ai`` should import from ``engine`` rather than reaching into submodules,
so the internal file layout stays free to change.
"""

from engine.models import (
    DIRECTION_VECTORS,
    Action,
    Contact,
    ContactKind,
    Coord,
    Detonation,
    Direction,
    Emission,
    EmissionKind,
    Fire,
    GameState,
    Move,
    Outcome,
    Ping,
    PlayerId,
    RangeBucket,
    RoundEvents,
    RoundResult,
    RunSilent,
    ShipState,
)
from engine.placement import new_match, place_ships
from engine.resolve import resolve
from engine.validation import InvalidAction, validate_action

__all__ = [
    "DIRECTION_VECTORS",
    "Action",
    "Contact",
    "ContactKind",
    "Coord",
    "Detonation",
    "Direction",
    "Emission",
    "EmissionKind",
    "Fire",
    "GameState",
    "InvalidAction",
    "Move",
    "Outcome",
    "Ping",
    "PlayerId",
    "RangeBucket",
    "RoundEvents",
    "RoundResult",
    "RunSilent",
    "ShipState",
    "new_match",
    "place_ships",
    "resolve",
    "validate_action",
]
