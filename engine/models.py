"""The data model: the truth the server holds, and the vocabulary of a round.

Everything here is a frozen dataclass or an enum. Immutability is not decoration
— ``engine`` and ``perception`` are only *pure* if nothing can mutate a state
object behind their back, and ``resolve`` is only trustworthy if it demonstrably
returns a new state rather than editing the one it was handed.

The single most important line in this file is the comment on
``GameState.ships``: that is the truth, and it never reaches a response body.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from config import DEFAULT, GameConfig

Coord = tuple[int, int]
"""An (x, y) grid cell. x runs east, y runs north — see DIRECTION_VECTORS."""


class PlayerId(StrEnum):
    """The two seats in a match.

    A StrEnum rather than a bare string so that a typo is an AttributeError at
    import time instead of a silently missing dict key at round three.
    """

    P1 = "P1"
    P2 = "P2"

    @property
    def other(self) -> PlayerId:
        """The opponent. Saves every call site an if/else it could get wrong."""
        return PlayerId.P2 if self is PlayerId.P1 else PlayerId.P1


Direction = Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

DIRECTION_VECTORS: Mapping[Direction, Coord] = {
    "N": (0, 1),
    "NE": (1, 1),
    "E": (1, 0),
    "SE": (1, -1),
    "S": (0, -1),
    "SW": (-1, -1),
    "W": (-1, 0),
    "NW": (-1, 1),
}
"""Unit step per compass direction, scaled by ``move_distance`` on a Move.

y increases northward. This is fixed by the bearing convention in PRD §4
(0 deg = east, 90 deg = north, measured counter-clockwise): the worked example
takes a ship at (10,10) and an enemy at (16,13) to bear atan2(3, 6) ~= 26.6 deg
and calls it northeast, which only holds if +y is north.
"""


# --- Actions ---------------------------------------------------------------
# One of these four per player per round, chosen in secret. Modelled as separate
# frozen types rather than one class with optional fields so that an action
# carrying the wrong parameters (a Move with a target, a Fire with no target) is
# not constructible in the first place.


@dataclass(frozen=True, slots=True)
class RunSilent:
    """Hold position and listen. Emits nothing — the only invisible action."""


@dataclass(frozen=True, slots=True)
class Move:
    """Burn ``move_distance`` cells in one of eight directions. Emits HEAT."""

    direction: Direction


@dataclass(frozen=True, slots=True)
class Ping:
    """Active sonar. Emits PING, which hands the enemy your exact cell."""


@dataclass(frozen=True, slots=True)
class Fire:
    """Detonate a blast centred on any named cell. Emits LAUNCH.

    The target is deliberately unconstrained beyond being on-grid: blind-firing
    at a guess is a legal and central move.
    """

    target: Coord


Action = RunSilent | Move | Ping | Fire


# --- Ships and the world ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShipState:
    """One ship's true state. Only ever revealed to its own captain.

    ``heading`` from design §2.2 is deliberately omitted: the design marks it
    "informational / flavour; not required for v1 rules", and PRD §6 pins the
    serialized shape of ``your_ship`` to exactly position / hull / alive.
    """

    position: Coord
    hull: int
    alive: bool = True


class Outcome(StrEnum):
    """How the match stands, stated absolutely.

    ``perception`` translates this into the player-relative
    ONGOING / WIN / LOSS / DRAW that PRD §6 puts in a PlayerView. Keeping the
    engine's version absolute means the engine never has to know who is asking.
    """

    ONGOING = "ONGOING"
    P1_WINS = "P1_WINS"
    P2_WINS = "P2_WINS"
    DRAW = "DRAW"


@dataclass(frozen=True, slots=True)
class GameState:
    """The full truth. Lives only on the server. NEVER serialized into a body.

    Every field of ``ships`` is a true position. The one and only thing an
    endpoint returns to a player is a PlayerView built by ``perception``.
    """

    ships: Mapping[PlayerId, ShipState]
    round: int
    rng_seed: int
    """The match seed, kept so a match can be replayed exactly. Server-only.

    ``resolve`` takes a live ``random.Random`` rather than re-seeding from this
    each round — re-seeding per round would replay the same noise sequence every
    round, which is the opposite of what a seeded PRNG is for. This field is the
    record of where that stream started, and is never sent to a client.
    """

    outcome: Outcome = Outcome.ONGOING
    config: GameConfig = DEFAULT


# --- What a round produces -------------------------------------------------


EmissionKind = Literal["HEAT", "LAUNCH", "PING"]


@dataclass(frozen=True, slots=True)
class Emission:
    """A detectable signature left at a ship's post-movement position.

    The engine records these; ``perception`` decides who is close enough to hear
    one and how badly to degrade it. That split is why the engine needs no
    sensor maths and the fog filter needs no game rules.
    """

    source: PlayerId
    kind: EmissionKind
    position: Coord


@dataclass(frozen=True, slots=True)
class Detonation:
    """A torpedo going off at a named cell, and who it caught."""

    source: PlayerId
    target: Coord
    caught: tuple[PlayerId, ...]


ContactKind = Literal["PASSIVE_BEARING", "ACTIVE_FIX", "PING_DETECTED", "LAUNCH_DETECTED"]
RangeBucket = Literal["CLOSE", "MEDIUM", "FAR"]


@dataclass(frozen=True, slots=True)
class Contact:
    """Everything a player is permitted to perceive about the enemy.

    ``exact_position`` is set ONLY for ACTIVE_FIX (you pinged, enemy in range)
    and PING_DETECTED (enemy pinged). For PASSIVE_BEARING and LAUNCH_DETECTED it
    is structurally None — the closest the fog ever comes to betraying the enemy
    is a sharp-but-still-noised bearing at point-blank range.

    Populated by ``perception`` in phase 2; defined here because ``RoundResult``
    references it and the engine owns the shared vocabulary.
    """

    kind: ContactKind
    bearing_deg: float | None = None
    range_bucket: RangeBucket | None = None
    exact_position: Coord | None = None


@dataclass(frozen=True, slots=True)
class RoundResult:
    """What one player learns about the round that just resolved.

    Player-relative on purpose: "you" is whoever this result is keyed to. It
    reports outcomes, never positions.
    """

    you_were_hit: bool
    you_hit_enemy: bool
    your_ping_result: Contact | None = None
    """Filled by ``perception`` in phase 2 — the engine does no range gating."""


@dataclass(frozen=True, slots=True)
class RoundEvents:
    """The engine's record of one resolved round.

    This is the detection *hook*: ``emissions`` is the raw material
    ``perception.view_for`` turns into contacts. The engine states what happened;
    it does not decide who gets to know it.
    """

    round: int
    emissions: tuple[Emission, ...]
    detonations: tuple[Detonation, ...]
    results: Mapping[PlayerId, RoundResult]
