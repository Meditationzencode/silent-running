from dataclasses import FrozenInstanceError, replace

import pytest

from config import DEFAULT, GameConfig


def test_defaults_match_the_spec() -> None:
    assert DEFAULT.grid_size == 25
    assert DEFAULT.move_distance == 2
    assert DEFAULT.ping_range == 12.0
    assert DEFAULT.passive_range == 18.0
    assert DEFAULT.blast_radius == 1
    assert DEFAULT.hull == 2
    assert DEFAULT.bearing_base_err_deg == 4.0
    assert DEFAULT.bearing_err_per_cell_deg == 0.6
    assert DEFAULT.round_cap == 50
    assert DEFAULT.turn_timeout_s == 90.0
    assert DEFAULT.poll_interval_s == 1.0


def test_participation_thresholds() -> None:
    assert DEFAULT.max_consecutive_timeouts == 3
    assert DEFAULT.grace_window_s == 60.0
    assert DEFAULT.abandon_after_s == 180.0


def test_a_player_is_abandoned_only_well_after_they_are_merely_quiet() -> None:
    assert DEFAULT.grace_window_s < DEFAULT.abandon_after_s


def test_a_present_but_idle_player_forfeits_before_they_look_abandoned() -> None:
    """Otherwise the three-strike rule could never fire: absence would win first.

    Someone who polls but never acts keeps their liveness fresh, so only the
    turn timeout applies to them - and three of those must be reachable.
    """
    assert (
        DEFAULT.max_consecutive_timeouts * DEFAULT.turn_timeout_s
        > DEFAULT.abandon_after_s
    )


def test_range_bucket_boundaries_match_the_sensor_model() -> None:
    assert DEFAULT.bucket_close_max == 6.0
    assert DEFAULT.bucket_medium_max == 12.0
    assert DEFAULT.bucket_close_max < DEFAULT.bucket_medium_max < DEFAULT.passive_range


def test_config_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        DEFAULT.hull = 3


def test_a_variant_can_be_built_without_touching_the_default() -> None:
    one_shot_kill = replace(DEFAULT, hull=1)
    assert isinstance(one_shot_kill, GameConfig)
    assert one_shot_kill.hull == 1
    assert one_shot_kill.grid_size == DEFAULT.grid_size
    assert DEFAULT.hull == 2
