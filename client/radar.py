from __future__ import annotations

import sys
from collections import deque
from typing import Any

from config import DEFAULT, GameConfig
from engine import Coord
from engine.geometry import angular_gap, euclidean_distance
from perception import bearing_sigma_deg, range_bucket, true_bearing_deg

ARC_SIGMAS = 1.5

EMPTY = "."
YOU = "@"
HEAT = "o"
LAUNCH = "!"
FIX = "X"
ECHO_RECENT = ":"
ECHO_STALE = ","

HISTORY_DEPTH = 3

RESET = "\x1b[0m"
CLEAR_SCREEN = "\x1b[2J\x1b[H"
STYLES = {
    EMPTY: "\x1b[90m",
    YOU: "\x1b[1;96m",
    HEAT: "\x1b[1;93m",
    LAUNCH: "\x1b[1;91m",
    FIX: "\x1b[1;95m",
    ECHO_RECENT: "\x1b[33m",
    ECHO_STALE: "\x1b[2;33m",
}

COMPASS_16 = (
    "E", "ENE", "NE", "NNE", "N", "NNW", "NW", "WNW",
    "W", "WSW", "SW", "SSW", "S", "SSE", "SE", "ESE",
)

OPPONENT_LABEL = {
    "CONNECTED": "opponent connected",
    "DISCONNECTED_GRACE": "opponent gone quiet",
    "ABANDONED": "opponent abandoned",
}


def supports_colour(stream: Any = None) -> bool:
    """Colour only when writing to a real terminal, so piped output stays clean."""
    target = sys.stdout if stream is None else stream
    return bool(getattr(target, "isatty", lambda: False)())


def paint(symbol: str, colour: bool) -> str:
    if not colour or symbol not in STYLES:
        return symbol
    return f"{STYLES[symbol]}{symbol}{RESET}"


def compass_name(bearing_deg: float) -> str:
    """A bearing as a 16-point compass name, which reads faster than degrees."""
    return COMPASS_16[round(bearing_deg / 22.5) % 16]


def arc_cells(
    origin: Coord, bearing_deg: float, bucket: str, config: GameConfig = DEFAULT
) -> set[Coord]:
    """Every cell consistent with a noised bearing and its coarse range bucket.

    This is the honest picture of what a degraded contact says. Plotting a
    single blip at the reported bearing would draw a precision the sensor never
    claimed; the arc is wide where the noise is wide, so a distant contact
    smears across the board and a close one tightens to a wedge.
    """
    cells: set[Coord] = set()
    for x in range(config.grid_size):
        for y in range(config.grid_size):
            distance = euclidean_distance(origin, (x, y))
            if distance == 0.0 or range_bucket(distance, config) != bucket:
                continue
            spread = ARC_SIGMAS * bearing_sigma_deg(distance, config)
            if angular_gap(true_bearing_deg(origin, (x, y)), bearing_deg) <= spread:
                cells.add((x, y))
    return cells


class Plot:
    """What you have heard lately, and where you were standing when you heard it.

    An arc has to be drawn from the position it was taken from, so the origin is
    kept with the contact. Two arcs recorded from two different cells intersect,
    and that intersection is the whole of triangulation - the thing the bots do
    with a belief set and a human previously had to do from memory.
    """

    def __init__(self, depth: int = HISTORY_DEPTH) -> None:
        self.entries: deque[tuple[int, Coord, list[dict[str, Any]]]] = deque(
            maxlen=depth
        )

    def record(self, view: dict[str, Any]) -> None:
        """Remember this round's bearings. Ignores a round already recorded."""
        round_number = view["round"]
        if self.entries and self.entries[-1][0] == round_number:
            return
        self.entries.append(
            (
                round_number,
                tuple(view["your_ship"]["position"]),
                [c for c in view["contacts"] if c["bearing_deg"] is not None],
            )
        )

    def aged(self) -> list[tuple[int, Coord, dict[str, Any]]]:
        """Every remembered contact with its age in rounds, oldest first."""
        newest = len(self.entries) - 1
        return [
            (newest - index, origin, contact)
            for index, (_, origin, contacts) in enumerate(self.entries)
            for contact in contacts
        ]


def arc_symbol(age: int, kind: str) -> str:
    """Fresh contacts keep their kind; older ones fade into generic echoes."""
    if age == 0:
        return LAUNCH if kind == "LAUNCH_DETECTED" else HEAT
    return ECHO_RECENT if age == 1 else ECHO_STALE


def overlay(
    view: dict[str, Any], config: GameConfig = DEFAULT, plot: Plot | None = None
) -> dict[Coord, str]:
    """Map each cell to the symbol it should carry, strongest evidence winning."""
    own = tuple(view["your_ship"]["position"])
    marks: dict[Coord, str] = {}

    remembered = (
        plot.aged()
        if plot is not None
        else [(0, own, c) for c in view["contacts"] if c["bearing_deg"] is not None]
    )

    # Oldest first, so a fresh reading paints over a stale one on shared cells.
    for age, origin, contact in sorted(remembered, key=lambda item: -item[0]):
        for cell in arc_cells(
            origin, contact["bearing_deg"], contact["range_bucket"], config
        ):
            marks[cell] = arc_symbol(age, contact["kind"])

    for contact in view["contacts"]:
        if contact["exact_position"] is not None:
            marks[tuple(contact["exact_position"])] = FIX

    marks[own] = YOU
    return marks


def grid_lines(
    view: dict[str, Any],
    config: GameConfig = DEFAULT,
    colour: bool = True,
    plot: Plot | None = None,
) -> list[str]:
    """The board, drawn with y increasing upward so north is up."""
    marks = overlay(view, config, plot)
    size = config.grid_size

    # Two header rows, tens over units, so a column can be read off directly.
    # Firing means typing a cell, so every axis is labelled rather than every
    # fifth: counting squares is not the difficulty this game is about.
    lines = [
        "    " + " ".join(str(x // 10) if x >= 10 else " " for x in range(size)),
        "    " + " ".join(str(x % 10) for x in range(size)),
    ]
    for y in range(size - 1, -1, -1):
        row = " ".join(paint(marks.get((x, y), EMPTY), colour) for x in range(size))
        lines.append(f"{y:>3} {row}")
    return lines


def describe(contact: dict[str, Any]) -> str:
    """One contact in words, saying only as much as the sensor granted."""
    kind = contact["kind"].replace("_", " ").lower()
    if contact["exact_position"] is not None:
        x, y = contact["exact_position"]
        return f"{kind}: exact fix at ({x},{y})"
    return (
        f"{kind}: {contact['bearing_deg']:.1f} deg "
        f"({compass_name(contact['bearing_deg'])}), "
        f"{contact['range_bucket'].lower()} range"
    )


def status_lines(view: dict[str, Any]) -> list[str]:
    ship = view["your_ship"]
    x, y = ship["position"]
    lines = [f"  you ({x},{y})   hull {ship['hull']}"]

    result = view["last_result"]
    if result is not None and (result["you_hit_enemy"] or result["you_were_hit"]):
        if result["you_hit_enemy"]:
            lines.append("  >> your torpedo connected")
        if result["you_were_hit"]:
            lines.append("  >> YOU WERE HIT")

    if view["contacts"]:
        lines.extend(f"  * {describe(contact)}" for contact in view["contacts"])
    else:
        lines.append("  * nothing on the sensors")
    return lines


def render(
    view: dict[str, Any],
    config: GameConfig = DEFAULT,
    colour: bool = True,
    plot: Plot | None = None,
) -> str:
    """A whole frame: the board, then what it means."""
    opponent = OPPONENT_LABEL.get(view["opponent_status"], view["opponent_status"])
    frame = [
        "",
        f"  round {view['round']}   {view['phase']}   {opponent}",
        "",
        *grid_lines(view, config, colour, plot),
        "",
        f"  {YOU} you   {HEAT} heat   {LAUNCH} launch   {FIX} fix"
        f"   {ECHO_RECENT} last round   {ECHO_STALE} older",
        "",
        *status_lines(view),
    ]
    if view["outcome"] != "ONGOING":
        frame += ["", f"  ===  {view['outcome']}  ==="]
    else:
        frame += ["", "  m <dir>   f <x> <y>   p ping   s silent   q resign"]
    return "\n".join(frame)
