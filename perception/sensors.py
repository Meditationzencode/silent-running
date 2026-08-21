from __future__ import annotations

import math
import random

from config import DEFAULT, GameConfig
from engine import Contact, Coord, RangeBucket
from engine.geometry import euclidean_distance

BEARING_DECIMALS = 1


def true_bearing_deg(origin: Coord, target: Coord) -> float:
    dx = target[0] - origin[0]
    dy = target[1] - origin[1]
    return math.degrees(math.atan2(dy, dx)) % 360.0


def bearing_sigma_deg(distance: float, config: GameConfig = DEFAULT) -> float:
    return config.bearing_base_err_deg + config.bearing_err_per_cell_deg * distance


def noised_bearing_deg(
    origin: Coord, target: Coord, rng: random.Random, config: GameConfig = DEFAULT
) -> float:
    distance = euclidean_distance(origin, target)
    sigma = bearing_sigma_deg(distance, config)
    noised = true_bearing_deg(origin, target) + rng.gauss(0.0, sigma)

    return round(noised % 360.0, BEARING_DECIMALS) % 360.0


def range_bucket(
    distance: float, config: GameConfig = DEFAULT
) -> RangeBucket | None:
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
    return Contact(kind="PING_DETECTED", exact_position=pinger)


def active_fix(
    pinger: Coord, enemy: Coord, config: GameConfig = DEFAULT
) -> Contact | None:
    if euclidean_distance(pinger, enemy) > config.ping_range:
        return None
    return Contact(kind="ACTIVE_FIX", exact_position=enemy)
