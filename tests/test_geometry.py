"""The two distance metrics, pinned against the spec's worked examples.

Worth testing separately because using the wrong one is a silent, plausible bug:
Euclidean blast geometry would quietly make the torpedo a plus-shape, and
Chebyshev ranging would quietly widen every sensor bucket on the diagonals.
"""

from __future__ import annotations

import pytest

from engine.geometry import (
    chebyshev_distance,
    clamp_to_grid,
    euclidean_distance,
    on_grid,
)
from engine.models import Coord


def test_euclidean_matches_the_prd_worked_example() -> None:
    """PRD §4: your ship (10,10), enemy (16,13), separation ~= 6.7 cells."""
    assert euclidean_distance((10, 10), (16, 13)) == pytest.approx(6.708, abs=1e-3)


def test_euclidean_is_symmetric_and_zero_on_the_same_cell() -> None:
    assert euclidean_distance((3, 4), (0, 0)) == pytest.approx(5.0)
    assert euclidean_distance((0, 0), (3, 4)) == pytest.approx(5.0)
    assert euclidean_distance((7, 7), (7, 7)) == 0.0


def test_the_two_metrics_disagree_on_diagonals() -> None:
    """The reason both exist: a diagonal neighbour is 1 king-move but 1.41 away."""
    diagonal: Coord = (1, 1)
    assert chebyshev_distance((0, 0), diagonal) == 1
    assert euclidean_distance((0, 0), diagonal) == pytest.approx(2**0.5)


@pytest.mark.parametrize(
    ("value", "expected"), [(-5, 0), (-1, 0), (0, 0), (12, 12), (24, 24), (25, 24)]
)
def test_clamp_keeps_an_axis_inside_the_grid(value: int, expected: int) -> None:
    assert clamp_to_grid(value, 25) == expected


@pytest.mark.parametrize("cell", [(0, 0), (24, 24), (0, 24), (24, 0)])
def test_corners_are_on_grid(cell: Coord) -> None:
    assert on_grid(cell)


@pytest.mark.parametrize("cell", [(-1, 0), (0, -1), (25, 0), (0, 25)])
def test_cells_past_an_edge_are_off_grid(cell: Coord) -> None:
    assert not on_grid(cell)
