from __future__ import annotations

import math

from config import DEFAULT, GameConfig
from engine.models import Coord


def clamp_to_grid(value: int, grid_size: int) -> int:
    return max(0, min(value, grid_size - 1))


def on_grid(cell: Coord, config: GameConfig = DEFAULT) -> bool:
    x, y = cell
    return 0 <= x < config.grid_size and 0 <= y < config.grid_size


def chebyshev_distance(a: Coord, b: Coord) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def euclidean_distance(a: Coord, b: Coord) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
