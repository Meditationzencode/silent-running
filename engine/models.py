from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from config import DEFAULT, GameConfig

Coord = tuple[int, int]


class PlayerId(StrEnum):
    P1 = "P1"
    P2 = "P2"

    @property
    def other(self) -> PlayerId:
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


@dataclass(frozen=True, slots=True)
class RunSilent:
    pass


@dataclass(frozen=True, slots=True)
class Move:
    direction: Direction


@dataclass(frozen=True, slots=True)
class Ping:
    pass


@dataclass(frozen=True, slots=True)
class Fire:
    target: Coord


Action = RunSilent | Move | Ping | Fire


@dataclass(frozen=True, slots=True)
class ShipState:
    position: Coord
    hull: int
    alive: bool = True


class Outcome(StrEnum):
    ONGOING = "ONGOING"
    P1_WINS = "P1_WINS"
    P2_WINS = "P2_WINS"
    DRAW = "DRAW"


@dataclass(frozen=True, slots=True)
class GameState:
    ships: Mapping[PlayerId, ShipState]
    round: int
    rng_seed: int
    outcome: Outcome = Outcome.ONGOING
    config: GameConfig = DEFAULT
    last_events: RoundEvents | None = None


EmissionKind = Literal["HEAT", "LAUNCH", "PING"]


@dataclass(frozen=True, slots=True)
class Emission:
    source: PlayerId
    kind: EmissionKind
    position: Coord


@dataclass(frozen=True, slots=True)
class Detonation:
    source: PlayerId
    target: Coord
    caught: tuple[PlayerId, ...]


ContactKind = Literal["PASSIVE_BEARING", "ACTIVE_FIX", "PING_DETECTED", "LAUNCH_DETECTED"]
RangeBucket = Literal["CLOSE", "MEDIUM", "FAR"]


@dataclass(frozen=True, slots=True)
class Contact:
    kind: ContactKind
    bearing_deg: float | None = None
    range_bucket: RangeBucket | None = None
    exact_position: Coord | None = None


@dataclass(frozen=True, slots=True)
class RoundResult:
    you_were_hit: bool
    you_hit_enemy: bool


@dataclass(frozen=True, slots=True)
class RoundEvents:
    round: int
    emissions: tuple[Emission, ...]
    detonations: tuple[Detonation, ...]
    results: Mapping[PlayerId, RoundResult]
