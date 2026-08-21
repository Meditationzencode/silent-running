from __future__ import annotations

import pytest

from config import DEFAULT
from engine.models import DIRECTION_VECTORS, Fire, Move, Ping, RunSilent
from engine.validation import InvalidAction, validate_action


@pytest.mark.parametrize("direction", sorted(DIRECTION_VECTORS))
def test_all_eight_compass_directions_are_legal(direction: str) -> None:
    validate_action(Move(direction))


@pytest.mark.parametrize("direction", ["UP", "n", "NNE", "", "NE ", "north"])
def test_an_unknown_direction_is_rejected(direction: str) -> None:
    with pytest.raises(InvalidAction) as excinfo:
        validate_action(Move(direction))

    assert excinfo.value.code == "invalid_direction"


@pytest.mark.parametrize("target", [(0, 0), (24, 24), (0, 24), (24, 0), (12, 12)])
def test_any_on_grid_cell_is_a_legal_target(target: tuple[int, int]) -> None:
    validate_action(Fire(target))


@pytest.mark.parametrize("target", [(26, 4), (-1, 0), (0, -1), (25, 24), (24, 25)])
def test_an_off_grid_target_is_rejected(target: tuple[int, int]) -> None:
    with pytest.raises(InvalidAction) as excinfo:
        validate_action(Fire(target))

    assert excinfo.value.code == "target_out_of_bounds"
    assert "off-grid" in excinfo.value.detail


def test_a_structurally_broken_target_is_rejected() -> None:
    for bad in [(1,), (1, 2, 3), "12", (1.5, 2.0), (True, False), None]:
        with pytest.raises(InvalidAction) as excinfo:
            validate_action(Fire(bad))
        assert excinfo.value.code == "target_out_of_bounds"


def test_parameterless_actions_are_always_legal() -> None:
    validate_action(RunSilent())
    validate_action(Ping())


def test_firing_at_your_own_cell_is_legal() -> None:
    validate_action(Fire((10, 10)))


def test_an_unknown_action_type_is_rejected() -> None:
    with pytest.raises(InvalidAction) as excinfo:
        validate_action(object())

    assert excinfo.value.code == "invalid_action"


def test_bounds_follow_the_config_not_a_hardcoded_25() -> None:
    from dataclasses import replace

    small = replace(DEFAULT, grid_size=10)
    validate_action(Fire((9, 9)), small)

    with pytest.raises(InvalidAction):
        validate_action(Fire((10, 9)), small)
