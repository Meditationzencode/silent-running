from __future__ import annotations

import re

import pytest

from client.radar import (
    ECHO_RECENT,
    ECHO_STALE,
    FIX,
    HEAT,
    YOU,
    Plot,
    arc_cells,
    arc_symbol,
    compass_name,
    describe,
    overlay,
    render,
)
from client.terminal import parse_action
from config import DEFAULT
from engine.geometry import angular_gap, euclidean_distance
from perception import range_bucket, true_bearing_deg

QUIET_VIEW = {
    "round": 4,
    "phase": "RESOLVED",
    "your_ship": {"position": [10, 10], "hull": 1, "alive": True},
    "contacts": [],
    "last_result": None,
    "opponent_status": "CONNECTED",
    "outcome": "ONGOING",
}


def with_contacts(*contacts: dict) -> dict:
    return {**QUIET_VIEW, "contacts": list(contacts)}


def bearing_contact(bearing: float, bucket: str) -> dict:
    return {
        "kind": "PASSIVE_BEARING",
        "bearing_deg": bearing,
        "range_bucket": bucket,
        "exact_position": None,
    }


# --- Command parsing --------------------------------------------------------


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


# --- Bearings as pictures ---------------------------------------------------


@pytest.mark.parametrize(
    ("bearing", "name"),
    [(0.0, "E"), (45.0, "NE"), (90.0, "N"), (180.0, "W"), (270.0, "S"), (67.5, "NNE")],
)
def test_a_bearing_reads_as_a_compass_point(bearing: float, name: str) -> None:
    assert compass_name(bearing) == name


def test_an_arc_only_covers_cells_in_the_reported_bucket() -> None:
    cells = arc_cells((10, 10), 45.0, "CLOSE")

    assert cells
    assert all(range_bucket(euclidean_distance((10, 10), c)) == "CLOSE" for c in cells)


def test_an_arc_widens_with_range() -> None:
    """The picture has to be as vague as the reading behind it.

    Fired from near the south edge looking north, so a FAR arc has room to open
    up instead of being clipped by the board.
    """

    def widest(bucket: str) -> float:
        cells = arc_cells((12, 2), 90.0, bucket)
        return max(angular_gap(true_bearing_deg((12, 2), c), 90.0) for c in cells)

    assert widest("FAR") > widest("MEDIUM") > widest("CLOSE")


def test_an_arc_is_centred_on_the_reported_bearing() -> None:
    cells = arc_cells((12, 2), 90.0, "MEDIUM")

    assert all(c[1] > 2 for c in cells)
    assert any(c[0] == 12 for c in cells)


# --- The overlay ------------------------------------------------------------


def test_your_own_ship_is_always_drawn() -> None:
    assert overlay(QUIET_VIEW)[(10, 10)] == YOU


def test_a_degraded_contact_is_drawn_as_an_area_not_a_point() -> None:
    marks = overlay(with_contacts(bearing_contact(45.0, "MEDIUM")))

    assert sum(1 for symbol in marks.values() if symbol == HEAT) > 10


def test_an_exact_fix_is_drawn_as_a_single_cell() -> None:
    marks = overlay(
        with_contacts(
            {
                "kind": "ACTIVE_FIX",
                "bearing_deg": None,
                "range_bucket": None,
                "exact_position": [16, 13],
            }
        )
    )

    assert marks[(16, 13)] == FIX
    assert sum(1 for symbol in marks.values() if symbol == FIX) == 1


def test_an_exact_fix_wins_over_an_arc_covering_the_same_cell() -> None:
    marks = overlay(
        with_contacts(
            bearing_contact(45.0, "MEDIUM"),
            {
                "kind": "PING_DETECTED",
                "bearing_deg": None,
                "range_bucket": None,
                "exact_position": [16, 16],
            },
        )
    )

    assert marks[(16, 16)] == FIX


# --- Memory: the plot that makes triangulation visible ---------------------


def moved_view(round_number: int, position: list[int], bearing: float) -> dict:
    return {
        **QUIET_VIEW,
        "round": round_number,
        "your_ship": {"position": position, "hull": 2, "alive": True},
        "contacts": [bearing_contact(bearing, "MEDIUM")],
    }


def test_a_plot_remembers_where_you_were_when_you_heard_it() -> None:
    plot = Plot()

    plot.record(moved_view(5, [4, 4], 50.0))
    plot.record(moved_view(6, [8, 4], 75.0))

    ages = plot.aged()
    assert [(age, origin) for age, origin, _ in ages] == [(1, (4, 4)), (0, (8, 4))]


def test_a_plot_ignores_a_round_it_has_already_seen() -> None:
    """Polling re-fetches the same view; that must not age the history."""
    plot = Plot()
    plot.record(moved_view(5, [4, 4], 50.0))
    plot.record(moved_view(5, [4, 4], 50.0))

    assert len(plot.entries) == 1


def test_a_plot_forgets_beyond_its_depth() -> None:
    plot = Plot(depth=2)

    for round_number in (1, 2, 3, 4):
        plot.record(moved_view(round_number, [4, 4], 50.0))

    assert len(plot.entries) == 2
    assert [entry[0] for entry in plot.entries] == [3, 4]


@pytest.mark.parametrize(
    ("age", "kind", "symbol"),
    [
        (0, "PASSIVE_BEARING", HEAT),
        (0, "LAUNCH_DETECTED", "!"),
        (1, "PASSIVE_BEARING", ECHO_RECENT),
        (2, "LAUNCH_DETECTED", ECHO_STALE),
    ],
)
def test_a_contact_fades_with_age(age: int, kind: str, symbol: str) -> None:
    assert arc_symbol(age, kind) == symbol


def test_older_arcs_are_drawn_but_a_fresh_one_paints_over_them() -> None:
    plot = Plot()
    plot.record(moved_view(5, [4, 4], 50.0))
    plot.record(moved_view(6, [4, 4], 50.0))

    marks = overlay(moved_view(6, [4, 4], 50.0), plot=plot)
    drawn = set(marks.values())

    assert HEAT in drawn
    assert ECHO_RECENT not in drawn, "an identical rerecorded arc should be overpainted"


def test_two_arcs_from_different_positions_both_appear() -> None:
    """The intersection of these is what a player is meant to read off."""
    plot = Plot()
    plot.record(moved_view(5, [4, 4], 50.0))
    plot.record(moved_view(6, [12, 4], 130.0))

    marks = overlay(moved_view(6, [12, 4], 130.0), plot=plot)

    assert HEAT in marks.values()
    assert ECHO_RECENT in marks.values()


# --- The frame --------------------------------------------------------------


def test_the_frame_states_the_round_your_ship_and_the_phase() -> None:
    frame = render(QUIET_VIEW, colour=False)

    assert "round 4" in frame
    assert "RESOLVED" in frame
    assert "(10,10)" in frame
    assert "hull 1" in frame


def test_a_quiet_round_says_so() -> None:
    assert "nothing on the sensors" in render(QUIET_VIEW, colour=False)


def test_hits_are_called_out() -> None:
    view = {**QUIET_VIEW, "last_result": {"you_were_hit": True, "you_hit_enemy": True}}

    frame = render(view, colour=False)

    assert "your torpedo connected" in frame
    assert "YOU WERE HIT" in frame


def test_a_finished_match_gets_a_banner() -> None:
    assert "WIN" in render({**QUIET_VIEW, "outcome": "WIN"}, colour=False)


def test_the_grid_is_drawn_north_up() -> None:
    """y increases upward, so the top line of the board is row 24."""
    rows = [
        line
        for line in render(QUIET_VIEW, colour=False).splitlines()
        if re.fullmatch(r"\s*\d+(?: [.@o!X])+", line)
    ]

    assert len(rows) == DEFAULT.grid_size
    assert rows[0].split()[0] == "24"
    assert rows[-1].split()[0] == "0"


def test_colour_is_left_out_when_asked() -> None:
    assert "\x1b[" not in render(QUIET_VIEW, colour=False)


def test_colour_is_used_when_allowed() -> None:
    assert "\x1b[" in render(QUIET_VIEW, colour=True)


# --- The fog holds at the display layer too --------------------------------


def test_a_degraded_contact_is_never_described_with_a_cell() -> None:
    line = describe(bearing_contact(42.3, "CLOSE"))

    assert "42.3" in line
    assert "close" in line
    assert "(" in line and "NE" in line
    assert "," not in line.split("(")[1].split(")")[0]


def test_an_exact_fix_is_described_with_its_cell() -> None:
    line = describe(
        {
            "kind": "ACTIVE_FIX",
            "bearing_deg": None,
            "range_bucket": None,
            "exact_position": [16, 13],
        }
    )

    assert "(16,13)" in line


def test_the_display_never_invents_a_cell_for_a_bearing() -> None:
    """The arc may cover many cells; none of them is claimed as the answer."""
    frame = render(with_contacts(bearing_contact(42.3, "MEDIUM")), colour=False)
    reported = [line for line in frame.splitlines() if "passive bearing" in line]

    assert len(reported) == 1
    assert not re.search(r"\(\s*\d+\s*,\s*\d+\s*\)", reported[0])
