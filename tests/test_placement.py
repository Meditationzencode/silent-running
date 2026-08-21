from __future__ import annotations

import random
from dataclasses import replace

import pytest

from config import DEFAULT
from engine.geometry import chebyshev_distance, on_grid
from engine.models import Outcome, PlayerId
from engine.placement import MIN_START_SEPARATION, new_match, place_ships

SEEDS = range(200)


@pytest.mark.parametrize("seed", SEEDS)
def test_ships_start_on_grid_and_non_adjacent(seed: int) -> None:
    ships = place_ships(random.Random(seed))
    p1, p2 = ships[PlayerId.P1].position, ships[PlayerId.P2].position

    assert on_grid(p1)
    assert on_grid(p2)
    assert chebyshev_distance(p1, p2) >= MIN_START_SEPARATION


def test_placement_is_reproducible_from_the_seed() -> None:
    assert place_ships(random.Random(7)) == place_ships(random.Random(7))


def test_placement_actually_varies_between_seeds() -> None:
    boards = {
        (
            place_ships(random.Random(s))[PlayerId.P1].position,
            place_ships(random.Random(s))[PlayerId.P2].position,
        )
        for s in SEEDS
    }
    assert len(boards) > len(SEEDS) // 2


def test_ships_start_with_the_configured_hull() -> None:
    forgiving = replace(DEFAULT, hull=3)
    ships = place_ships(random.Random(1), forgiving)

    assert all(ship.hull == 3 and ship.alive for ship in ships.values())


@pytest.mark.parametrize("grid_size", [1, 2])
def test_a_grid_too_small_for_two_ships_is_refused(grid_size: int) -> None:
    with pytest.raises(ValueError, match="too small"):
        place_ships(random.Random(0), replace(DEFAULT, grid_size=grid_size))


def test_smallest_workable_grid_still_places_ships() -> None:
    ships = place_ships(random.Random(0), replace(DEFAULT, grid_size=3))
    positions = [ship.position for ship in ships.values()]

    assert chebyshev_distance(*positions) >= MIN_START_SEPARATION


def test_new_match_opens_at_round_one_and_records_the_seed() -> None:
    state = new_match(seed=1234)

    assert state.round == 1
    assert state.rng_seed == 1234
    assert state.outcome is Outcome.ONGOING
    assert set(state.ships) == {PlayerId.P1, PlayerId.P2}
