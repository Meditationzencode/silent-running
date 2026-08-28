from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod

from config import DEFAULT, GameConfig
from engine import Action, Contact, Coord, Direction
from engine.geometry import angular_gap, clamp_to_grid
from perception import PlayerView

COMPASS: tuple[Direction, ...] = ("E", "NE", "N", "NW", "W", "SW", "S", "SE")
EXACT_KINDS = ("ACTIVE_FIX", "PING_DETECTED")


class Bot(ABC):
    """A headless client: it sees a PlayerView and returns one Action.

    It has no GameState, no privileged sensor and no sight of the enemy. What it
    may know is what a human player knows: the rules and the tunables.
    """

    level: int
    name: str

    def __init__(
        self, rng: random.Random | None = None, config: GameConfig = DEFAULT
    ) -> None:
        self.rng = random.Random() if rng is None else rng
        self.config = config

    @abstractmethod
    def choose_action(self, view: PlayerView) -> Action:
        """Decide this round's action from the fogged view alone."""


def bearing_to_direction(bearing_deg: float) -> Direction:
    """Snap a bearing to the nearest of the eight compass directions."""
    return COMPASS[round(bearing_deg / 45.0) % 8]


def project(
    origin: Coord, bearing_deg: float, distance: float, config: GameConfig = DEFAULT
) -> Coord:
    """The on-grid cell that lies `distance` away from origin along a bearing."""
    radians = math.radians(bearing_deg)
    return (
        clamp_to_grid(round(origin[0] + distance * math.cos(radians)), config.grid_size),
        clamp_to_grid(round(origin[1] + distance * math.sin(radians)), config.grid_size),
    )


def bucket_bounds(bucket: str, config: GameConfig = DEFAULT) -> tuple[float, float]:
    """The distance range a coarse range bucket stands for."""
    if bucket == "CLOSE":
        return 0.0, config.bucket_close_max
    if bucket == "MEDIUM":
        return config.bucket_close_max, config.bucket_medium_max
    return config.bucket_medium_max, config.passive_range


def bucket_midpoint(bucket: str, config: GameConfig = DEFAULT) -> float:
    """A single best-guess distance for a bucket, for bots that do not track belief."""
    low, high = bucket_bounds(bucket, config)
    return (low + high) / 2.0


def exact_contact(view: PlayerView) -> Contact | None:
    """The contact carrying an exact enemy cell this round, if the round granted one."""
    for contact in view.contacts:
        if contact.kind in EXACT_KINDS and contact.exact_position is not None:
            return contact
    return None


def bearing_contact(view: PlayerView) -> Contact | None:
    """The degraded contact this round, if the enemy emitted within passive range."""
    for contact in view.contacts:
        if contact.bearing_deg is not None and contact.range_bucket is not None:
            return contact
    return None


def random_cell(rng: random.Random, config: GameConfig = DEFAULT) -> Coord:
    """A uniformly random on-grid cell."""
    return (rng.randrange(config.grid_size), rng.randrange(config.grid_size))


def random_direction(rng: random.Random) -> Direction:
    """One of the eight compass directions."""
    return rng.choice(COMPASS)
