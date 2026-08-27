from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Literal

from engine import Contact, RoundResult, ShipState

Phase = Literal["AWAITING_ACTIONS", "RESOLVED"]

OpponentStatus = Literal["CONNECTED", "DISCONNECTED_GRACE", "ABANDONED"]

PlayerOutcome = Literal["ONGOING", "WIN", "LOSS", "DRAW"]


@dataclass(frozen=True, slots=True)
class PlayerView:
    """What one player may see. There is deliberately no enemy-position field."""

    round: int
    phase: Phase
    your_ship: ShipState
    contacts: tuple[Contact, ...]
    last_result: RoundResult | None
    opponent_status: OpponentStatus
    outcome: PlayerOutcome


FORBIDDEN_FIELD_NAMES = frozenset({"enemy", "enemy_ship", "enemy_position", "ships"})


def to_payload(view: PlayerView) -> dict[str, Any]:
    """The exact response body, built field by field so no new field ships itself."""
    return {
        "round": view.round,
        "phase": view.phase,
        "your_ship": {
            "position": list(view.your_ship.position),
            "hull": view.your_ship.hull,
            "alive": view.your_ship.alive,
        },
        "contacts": [_contact_payload(contact) for contact in view.contacts],
        "last_result": (
            None
            if view.last_result is None
            else {
                "you_were_hit": view.last_result.you_were_hit,
                "you_hit_enemy": view.last_result.you_hit_enemy,
            }
        ),
        "opponent_status": view.opponent_status,
        "outcome": view.outcome,
    }


def _contact_payload(contact: Contact) -> dict[str, Any]:
    return {
        "kind": contact.kind,
        "bearing_deg": contact.bearing_deg,
        "range_bucket": contact.range_bucket,
        "exact_position": (
            None if contact.exact_position is None else list(contact.exact_position)
        ),
    }


def view_field_names() -> frozenset[str]:
    return frozenset(f.name for f in fields(PlayerView))
