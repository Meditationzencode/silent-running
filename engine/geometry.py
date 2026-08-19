"""Pure spatial helpers shared by the rules and (in phase 2) the fog filter.

Separated from ``models`` so that ``perception`` can import distance maths
without importing the game's rule types, and so the two distance metrics the
game uses are defined once, in one place, with the reason for each written down.
"""

from __future__ import annotations

import math

from config import DEFAULT, GameConfig
from engine.models import Coord


def clamp_to_grid(value: int, grid_size: int) -> int:
    """Clamp one axis into [0, grid_size - 1].

    Movement clamps rather than rejecting: PRD §3 is explicit that a Move which
    would carry a ship past an edge simply stops at the wall. Rejecting would
    leak information — a refused move tells the mover where the wall is, which
    they already know, but it would also stall the round.
    """
    return max(0, min(value, grid_size - 1))


def on_grid(cell: Coord, config: GameConfig = DEFAULT) -> bool:
    """True if the cell is inside (0,0)..(grid_size-1, grid_size-1)."""
    x, y = cell
    return 0 <= x < config.grid_size and 0 <= y < config.grid_size


def chebyshev_distance(a: Coord, b: Coord) -> int:
    """Max of the axis deltas — "how many king moves apart".

    This is the blast metric: a blast_radius of 1 under Chebyshev is exactly the
    3x3 footprint the design specifies. It is also the adjacency metric used for
    non-adjacent starting placement.
    """
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def euclidean_distance(a: Coord, b: Coord) -> float:
    """Straight-line distance — the *sensor* metric.

    Deliberately different from the blast metric. Ranges, range buckets and the
    bearing-noise term all scale with true straight-line distance, because they
    model sound travelling through space, not a piece moving on a board.
    """
    return math.hypot(a[0] - b[0], a[1] - b[1])
