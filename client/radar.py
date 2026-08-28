from __future__ import annotations

import sys
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

RESET = "\x1b[0m"
STYLES = {
    EMPTY: "\x1b[90m",
    YOU: "\x1b[1;96m",
    HEAT: "\x1b[93m",
    LAUNCH: "\x1b[1;91m",
    FIX: "\x1b[1;95m",
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


def overlay(view: dict[str, Any], config: GameConfig = DEFAULT) -> dict[Coord, str]:
    """Map each cell to the symbol it should carry, strongest evidence winning."""
    own = tuple(view["your_ship"]["position"])
    marks: dict[Coord, str] = {}

    for contact in view["contacts"]:
        if contact["exact_position"] is not None or contact["bearing_deg"] is None:
            continue
        symbol = LAUNCH if contact["kind"] == "LAUNCH_DETECTED" else HEAT
        for cell in arc_cells(
            own, contact["bearing_deg"], contact["range_bucket"], config
        ):
            marks.setdefault(cell, symbol)

    for contact in view["contacts"]:
        if contact["exact_position"] is not None:
            marks[tuple(contact["exact_position"])] = FIX

    marks[own] = YOU
    return marks


def grid_lines(
    view: dict[str, Any], config: GameConfig = DEFAULT, colour: bool = True
) -> list[str]:
    """The board, drawn with y increasing upward so north is up."""
    marks = overlay(view, config)
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
    view: dict[str, Any], config: GameConfig = DEFAULT, colour: bool = True
) -> str:
    """A whole frame: the board, then what it means."""
    opponent = OPPONENT_LABEL.get(view["opponent_status"], view["opponent_status"])
    frame = [
        "",
        f"  round {view['round']}   {view['phase']}   {opponent}",
        "",
        *grid_lines(view, config, colour),
        "",
        f"  {YOU} you    {HEAT} heat    {LAUNCH} launch    {FIX} exact fix",
        "",
        *status_lines(view),
    ]
    if view["outcome"] != "ONGOING":
        frame += ["", f"  ===  {view['outcome']}  ==="]
    return "\n".join(frame)
