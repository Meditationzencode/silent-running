"""Locks the default tunables to the agreed spec.

These numbers are a design contract, not implementation detail — the sensor
maths, the AI difficulty curve and the balance discussion all assume them. A
test here means an accidental edit shows up as a failure rather than as a subtly
different game.

It also serves as the Phase 0 smoke test: if this runs, the venv, the package
layout and the pytest/pythonpath wiring are all correct.
"""

from dataclasses import FrozenInstanceError, replace

import pytest

from config import DEFAULT, GameConfig


def test_defaults_match_the_spec() -> None:
    """Design doc §2.7, PRD §3-§5."""
    assert DEFAULT.grid_size == 25
    assert DEFAULT.move_distance == 2
    assert DEFAULT.ping_range == 12.0
    assert DEFAULT.passive_range == 18.0
    assert DEFAULT.blast_radius == 1
    assert DEFAULT.hull == 1
    assert DEFAULT.bearing_base_err_deg == 4.0
    assert DEFAULT.bearing_err_per_cell_deg == 0.6
    assert DEFAULT.round_cap == 50
    assert DEFAULT.turn_timeout_s == 90.0
    assert DEFAULT.poll_interval_s == 1.0


def test_range_bucket_boundaries_match_the_sensor_model() -> None:
    """CLOSE <= 6, MEDIUM 6-12, FAR 12-18, unheard beyond passive_range."""
    assert DEFAULT.bucket_close_max == 6.0
    assert DEFAULT.bucket_medium_max == 12.0
    assert DEFAULT.bucket_close_max < DEFAULT.bucket_medium_max < DEFAULT.passive_range


def test_config_is_immutable() -> None:
    """Purity depends on this: no layer may re-tune a live match's config."""
    with pytest.raises(FrozenInstanceError):
        DEFAULT.hull = 3  # type: ignore[misc]


def test_a_variant_can_be_built_without_touching_the_default() -> None:
    """How a more forgiving match (or a test) overrides one knob."""
    forgiving = replace(DEFAULT, hull=3)
    assert isinstance(forgiving, GameConfig)
    assert forgiving.hull == 3
    assert forgiving.grid_size == DEFAULT.grid_size
    assert DEFAULT.hull == 1
