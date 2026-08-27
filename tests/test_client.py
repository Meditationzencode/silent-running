from __future__ import annotations

import pytest

from client.terminal import describe, parse_action, render

BLANK_VIEW = {
    "round": 4,
    "phase": "RESOLVED",
    "your_ship": {"position": [10, 10], "hull": 1, "alive": True},
    "contacts": [],
    "last_result": None,
    "opponent_status": "CONNECTED",
    "outcome": "ONGOING",
}


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("s", {"type": "RUN_SILENT"}),
        ("silent", {"type": "RUN_SILENT"}),
        ("p", {"type": "PING"}),
        ("m ne", {"type": "MOVE", "direction": "NE"}),
        ("move SW", {"type": "MOVE", "direction": "SW"}),
        ("f 12 9", {"type": "FIRE", "target": [12, 9]}),
        ("  fire  0   24 ", {"type": "FIRE", "target": [0, 24]}),
    ],
)
def test_recognised_commands(line: str, expected: dict) -> None:
    assert parse_action(line) == expected


@pytest.mark.parametrize(
    "line", ["", "   ", "x", "m", "m NE extra", "f 1", "f a b", "fire 1 2 3"]
)
def test_unrecognised_commands_are_rejected_locally(line: str) -> None:
    assert parse_action(line) is None


def test_a_degraded_contact_is_shown_as_a_direction_not_a_place() -> None:
    line = describe(
        {
            "kind": "PASSIVE_BEARING",
            "bearing_deg": 42.3,
            "range_bucket": "CLOSE",
            "exact_position": None,
        }
    )

    assert "42.3" in line
    assert "close" in line
    assert "(" not in line


def test_an_exact_fix_is_shown_as_a_cell() -> None:
    line = describe(
        {
            "kind": "ACTIVE_FIX",
            "bearing_deg": None,
            "range_bucket": None,
            "exact_position": [16, 13],
        }
    )

    assert "(16,13)" in line


def test_a_quiet_round_says_so() -> None:
    assert "no contacts" in render(BLANK_VIEW)


def test_the_round_and_your_own_ship_are_always_shown() -> None:
    output = render(BLANK_VIEW)

    assert "round 4" in output
    assert "(10,10)" in output
    assert "hull 1" in output


def test_hits_are_called_out() -> None:
    view = dict(BLANK_VIEW)
    view["last_result"] = {"you_were_hit": True, "you_hit_enemy": True}

    output = render(view)

    assert "your torpedo connected" in output
    assert "you were hit" in output


def test_the_client_renders_only_what_a_playerview_carries() -> None:
    view = dict(BLANK_VIEW)
    view["contacts"] = [
        {
            "kind": "LAUNCH_DETECTED",
            "bearing_deg": 31.0,
            "range_bucket": "MEDIUM",
            "exact_position": None,
        }
    ]

    output = render(view)

    assert "launch detected" in output
    assert "31.0" in output
