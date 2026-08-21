"""The fog filter. Pure, deterministic, no I/O — and the hidden-state boundary.

``view_for(state, player, rng) -> PlayerView`` takes the full truth and returns
only what one player is allowed to perceive.

The invariant this package exists to enforce: the enemy's true position is a
field of ``GameState`` and **never** a field of any ``PlayerView``. The only way
an exact enemy coordinate reaches a player is inside a ``Contact`` of kind
``ACTIVE_FIX`` (you pinged, enemy in range) or ``PING_DETECTED`` (enemy pinged) —
the two cases where the sensor model legitimately grants it.

A Hypothesis property test asserts this across the input space; it must pass
before any networking work.
"""

from perception.models import (
    FORBIDDEN_FIELD_NAMES,
    OpponentStatus,
    Phase,
    PlayerOutcome,
    PlayerView,
    to_payload,
    view_field_names,
)
from perception.sensors import (
    active_fix,
    bearing_sigma_deg,
    noised_bearing_deg,
    passive_contact,
    ping_detected,
    range_bucket,
    true_bearing_deg,
)
from perception.view import view_for

__all__ = [
    "FORBIDDEN_FIELD_NAMES",
    "OpponentStatus",
    "Phase",
    "PlayerOutcome",
    "PlayerView",
    "active_fix",
    "bearing_sigma_deg",
    "noised_bearing_deg",
    "passive_contact",
    "ping_detected",
    "range_bucket",
    "to_payload",
    "true_bearing_deg",
    "view_field_names",
    "view_for",
]
