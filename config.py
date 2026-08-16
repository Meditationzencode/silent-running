"""Tunable game parameters — the single source of truth for balance.

Every rule in ``engine`` and every sensor calculation in ``perception`` reads its
numbers from here instead of hard-coding them, so the game can be re-balanced in
one place and discussed as one object.

Why a frozen dataclass rather than a module of loose constants:

* **Immutable.** ``engine`` and ``perception`` are pure and must stay that way.
  A frozen instance cannot be mutated at runtime by a later layer, so there is
  no hidden global that could make a "pure" function return different answers on
  two identical calls.
* **Injectable.** A test (or a more forgiving match) can construct a variant —
  ``replace(DEFAULT, hull=3)`` — and pass it in explicitly, rather than
  monkey-patching module globals.

Values come from the design document §2.7 and the PRD §3–§5.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GameConfig:
    """One match's tunables. All distances are in grid cells."""

    # --- Arena -------------------------------------------------------------
    grid_size: int = 25
    """Arena is grid_size x grid_size, coordinates (0,0)..(grid_size-1, grid_size-1)."""

    # --- Movement ----------------------------------------------------------
    move_distance: int = 2
    """Cells travelled by a Move, in one of the eight compass directions.

    A Move that would cross a grid edge is clamped to the boundary, not
    rejected — the ship simply stops at the wall (PRD §3).
    """

    # --- Sensors -----------------------------------------------------------
    ping_range: float = 12.0
    """Max range at which an Active Ping returns an ACTIVE_FIX on the enemy.

    A Ping emits regardless of outcome, so pinging beyond this range announces
    your exact position for nothing.
    """

    passive_range: float = 18.0
    """Beyond this range an emission is unheard entirely — no contact at all."""

    bucket_close_max: float = 6.0
    """Euclidean distance d <= this reports range_bucket CLOSE."""

    bucket_medium_max: float = 12.0
    """CLOSE_max < d <= this reports MEDIUM; above it, up to passive_range, FAR."""

    bearing_base_err_deg: float = 4.0
    """The constant term of the passive-bearing noise: sigma = base + k * d."""

    bearing_err_per_cell_deg: float = 0.6
    """``k`` — how fast bearing noise grows with distance, in degrees per cell.

    Distant contacts are barely a direction (sigma ~= 13 deg at 15 cells);
    close ones are fairly sharp (sigma ~= 7 deg at 5 cells). This gradient is
    what makes closing the distance worth the risk.
    """

    # --- Combat ------------------------------------------------------------
    blast_radius: int = 1
    """Chebyshev radius of a torpedo detonation: 1 gives the 3x3 blast."""

    hull: int = 1
    """Starting hull for both ships. 1 means one clean hit ends the match."""

    # --- Match flow --------------------------------------------------------
    round_cap: int = 50
    """Both ships still alive at this round number → draw.

    Exists only to terminate infinite mutual-silence stalemates.
    """

    turn_timeout_s: float = 90.0
    """Seconds from a round opening before a silent player is auto-Run Silent.

    Run Silent is the safe default: it emits nothing, so a timeout can never
    leak information the player did not choose to give away.
    """

    poll_interval_s: float = 1.0
    """Client-side only: how often the terminal client polls GET /view.

    Lives here so every tunable is in one place, but the server never reads it.
    """


DEFAULT = GameConfig()
"""The standard v1 balance. Pass a different GameConfig to vary a match."""
