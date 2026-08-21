from __future__ import annotations

import random

from config import DEFAULT, GameConfig
from engine.geometry import chebyshev_distance
from engine.models import Coord, GameState, PlayerId, ShipState

MIN_START_SEPARATION = 2


def place_ships(
    rng: random.Random, config: GameConfig = DEFAULT
) -> dict[PlayerId, ShipState]:
    cells = [(x, y) for x in range(config.grid_size) for y in range(config.grid_size)]
    first: Coord = rng.choice(cells)

    candidates = [
        cell
        for cell in cells
        if chebyshev_distance(cell, first) >= MIN_START_SEPARATION
    ]
    if not candidates:
        raise ValueError(
            f"grid_size {config.grid_size} is too small to place two "
            f"non-adjacent ships (needs at least {MIN_START_SEPARATION + 1})"
        )
    second: Coord = rng.choice(candidates)

    return {
        PlayerId.P1: ShipState(position=first, hull=config.hull),
        PlayerId.P2: ShipState(position=second, hull=config.hull),
    }


def new_match(seed: int, config: GameConfig = DEFAULT) -> GameState:
    return GameState(
        ships=place_ships(random.Random(seed), config),
        round=1,
        rng_seed=seed,
        config=config,
    )
