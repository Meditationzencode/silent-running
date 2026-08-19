"""Starting placement: random, non-adjacent, and told to nobody.

Placement is a *server* responsibility, not a negotiated setup phase (PRD §3).
That single decision removes a whole class of information-leak and turn-ordering
edge cases before the match even begins: there is no setup exchange to snoop on
and no first-placer advantage to balance.
"""

from __future__ import annotations

import random

from config import DEFAULT, GameConfig
from engine.geometry import chebyshev_distance
from engine.models import Coord, GameState, PlayerId, ShipState

MIN_START_SEPARATION = 2
"""Chebyshev cells. 2 is the smallest separation that is not "adjacent".

Design §2.1 asks only for non-adjacent, so this is the literal reading rather
than a comfort margin: two ships may legitimately open the match 2 cells apart,
well inside each other's blast radius. That is intended tension, not a bug.
"""


def place_ships(
    rng: random.Random, config: GameConfig = DEFAULT
) -> dict[PlayerId, ShipState]:
    """Pick two random, non-adjacent cells and build both ships' opening state.

    Enumerates the legal second cells rather than rejection-sampling. On a 25x25
    grid rejection would almost always succeed first try, but "almost always" is
    an unbounded loop on a small grid; enumerating is provably terminating and
    consumes exactly two draws from ``rng``, which keeps replays stable.
    """
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
    """Build the opening GameState for a match with the given server-only seed.

    The seed is threaded in rather than generated here so the caller (the server)
    owns it, can store it, and can replay a match exactly. It is never sent to a
    client.
    """
    return GameState(
        ships=place_ships(random.Random(seed), config),
        round=1,
        rng_seed=seed,
        config=config,
    )
