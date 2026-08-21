"""The sensor model: how truth is degraded before a player is allowed to see it.

Three rules, each a small pure function, so each can be tested against the
worked examples in PRD §4 without constructing a match.

The design decision worth defending here is that degradation happens *on the way
out*, at the moment a view is built, and not by storing an approximate position
anywhere. The server always holds exact truth; it just declines to say it. That
keeps one authoritative number in the system instead of a true one and a fuzzy
one that could drift apart.
"""

from __future__ import annotations

import math
import random

from config import DEFAULT, GameConfig
from engine import Contact, Coord, RangeBucket
from engine.geometry import euclidean_distance

BEARING_DECIMALS = 1
"""Reported bearing precision, matching the readouts in PRD §4 (42.3, 31.0).

A sensor that reported 42.31749283197 would be claiming a precision it does not
have. The rounding is cosmetic next to a sigma of 4-15 degrees, but a readout
should not look sharper than the instrument behind it.
"""


def true_bearing_deg(origin: Coord, target: Coord) -> float:
    """Exact bearing from origin to target, in [0, 360).

    Degrees counter-clockwise from due east (0 = E, 90 = N), per PRD §4. This
    value is never reported to a player — it is the input the noise is added to.
    """
    dx = target[0] - origin[0]
    dy = target[1] - origin[1]
    return math.degrees(math.atan2(dy, dx)) % 360.0


def bearing_sigma_deg(distance: float, config: GameConfig = DEFAULT) -> float:
    """Standard deviation of the bearing error at this range.

    ``sigma = base + k * d``. Growing the error with distance is what gives the
    game its central pressure: a contact at 5 cells is a fairly sharp direction
    (~7 deg), one at 15 cells is barely a direction at all (~13 deg). To sharpen
    a bearing you have to close the distance, and closing the distance means
    burning, and burning means emitting.
    """
    return config.bearing_base_err_deg + config.bearing_err_per_cell_deg * distance


def noised_bearing_deg(
    origin: Coord, target: Coord, rng: random.Random, config: GameConfig = DEFAULT
) -> float:
    """The bearing a listener is told: the truth plus Gaussian error.

    ``rng`` is the server's seeded stream. The seed never leaves the server, so a
    client cannot replay the noise to subtract it back off and recover the true
    bearing — the uncertainty is designed, not merely added.
    """
    distance = euclidean_distance(origin, target)
    sigma = bearing_sigma_deg(distance, config)
    noised = true_bearing_deg(origin, target) + rng.gauss(0.0, sigma)
    return round(noised % 360.0, BEARING_DECIMALS)


def range_bucket(
    distance: float, config: GameConfig = DEFAULT
) -> RangeBucket | None:
    """Coarse range, or None if the emission is out of passive range entirely.

    The bucket is exact but coarse: it tells you roughly how far, never where.
    Returning None past ``passive_range`` puts the audibility gate in the same
    function as the bucketing, so no caller can bucket a contact it should never
    have heard.

    Boundaries are continuous (d <= 6, 6 < d <= 12, 12 < d <= 18) as PRD §4
    specifies. Design §2.4 phrases them as integer spans ("MEDIUM 7-12"), which
    leaves a contact at 6.5 cells with no bucket; distances here are Euclidean
    and rarely whole, so the continuous reading is the one that works.
    """
    if distance <= config.bucket_close_max:
        return "CLOSE"
    if distance <= config.bucket_medium_max:
        return "MEDIUM"
    if distance <= config.passive_range:
        return "FAR"
    return None


def passive_contact(
    listener: Coord,
    emitter: Coord,
    kind: str,
    rng: random.Random,
    config: GameConfig = DEFAULT,
) -> Contact | None:
    """A bearing-only contact from a HEAT or LAUNCH emission, or None if unheard.

    ``exact_position`` is not merely left unset — it is structurally impossible
    for this function to grant one, because it never receives a reason to. A Move
    and a Fire are treated identically for detection: knowing a torpedo just left
    the tube and roughly which way is enough to fear, and not enough to
    counter-fire precisely.
    """
    distance = euclidean_distance(listener, emitter)
    bucket = range_bucket(distance, config)
    if bucket is None:
        return None

    return Contact(
        kind="PASSIVE_BEARING" if kind == "HEAT" else "LAUNCH_DETECTED",
        bearing_deg=noised_bearing_deg(listener, emitter, rng, config),
        range_bucket=bucket,
        exact_position=None,
    )


def ping_detected(pinger: Coord) -> Contact:
    """The contact handed to whoever the ping was aimed at. Always delivered.

    No range gate: a ping is loud, and the source is always revealed. Pinging
    from 24 cells away still tells the enemy exactly where you are — which is
    what makes a wasted ping so expensive.
    """
    return Contact(kind="PING_DETECTED", exact_position=pinger)


def active_fix(
    pinger: Coord, enemy: Coord, config: GameConfig = DEFAULT
) -> Contact | None:
    """The pinger's reward: an exact fix, but only if the enemy is in range.

    Out of ``ping_range`` the pinger gets nothing at all — while having emitted
    anyway. That asymmetry is the trade the whole game turns on.

    Takes no ``rng``: an exact fix is exact. There is nothing to degrade.
    """
    if euclidean_distance(pinger, enemy) > config.ping_range:
        return None
    return Contact(kind="ACTIVE_FIX", exact_position=enemy)
