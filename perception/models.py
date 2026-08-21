"""The PlayerView — the only thing an endpoint ever returns to a player.

Read the field list of ``PlayerView`` and notice what is not there: any way to
say where the enemy is. That absence is structural, not a matter of discipline.
A future contributor cannot accidentally populate an enemy-position field on a
view, because there is no such field to populate. The only exact enemy cell that
can reach a player travels inside a ``Contact``, and only for the two kinds the
sensor model legitimately grants.

``to_payload`` lives here rather than in ``server`` on purpose. The leak
invariant is asserted against "exactly the response body" (design §7), so the
dict the test inspects has to be the dict the endpoint actually returns — if the
server built its own, the proof would cover a serializer nobody ships. Turning
this dict into HTTP bytes is still the server's job; deciding what may appear in
it is the fog filter's.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Literal

from engine import Contact, RoundResult, ShipState

Phase = Literal["AWAITING_ACTIONS", "RESOLVED"]
"""Whether the server is still collecting actions for this round."""

OpponentStatus = Literal["CONNECTED", "DISCONNECTED_GRACE", "ABANDONED"]
"""Liveness of the other player. Owned by the server; filled in during phase 6."""

PlayerOutcome = Literal["ONGOING", "WIN", "LOSS", "DRAW"]
"""How the match stands *from this player's seat*.

The engine's ``Outcome`` is absolute (P1_WINS / P2_WINS) so it never has to know
who is asking. Translating it to WIN / LOSS is a perception job, because "who is
asking" is precisely the question this layer exists to answer.
"""


@dataclass(frozen=True, slots=True)
class PlayerView:
    """Everything one player is allowed to know, and nothing else.

    There is deliberately no enemy-position field. See the module docstring.
    """

    round: int
    phase: Phase
    your_ship: ShipState
    contacts: tuple[Contact, ...]
    last_result: RoundResult | None
    opponent_status: OpponentStatus
    outcome: PlayerOutcome


FORBIDDEN_FIELD_NAMES = frozenset({"enemy", "enemy_ship", "enemy_position", "ships"})
"""Names that would mean the view had grown a way to describe the enemy.

Asserted in the test suite. A guardrail against the specific regression this
project is about: someone adding "just one field" to make a client easier.
"""


def to_payload(view: PlayerView) -> dict[str, Any]:
    """Build the exact JSON-ready response body for this view.

    Written as an explicit field-by-field construction rather than
    ``dataclasses.asdict`` or a generic serializer. That is the whole point: a
    reflective serializer would faithfully emit whatever fields a future
    ``PlayerView`` happened to acquire, including one that leaks. This function
    only ever emits the seven keys PRD §6 specifies, so a leak would require
    someone to edit *this* function, deliberately, on a line that says so.
    """
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
    """Serialize one contact, exact position included only if one was granted.

    ``exact_position`` is emitted as-is: ``perception.sensors`` is responsible
    for it being None on every PASSIVE_BEARING and LAUNCH_DETECTED, and that
    responsibility is asserted structurally in the leak test rather than being
    re-checked here. One owner per rule.
    """
    return {
        "kind": contact.kind,
        "bearing_deg": contact.bearing_deg,
        "range_bucket": contact.range_bucket,
        "exact_position": (
            None if contact.exact_position is None else list(contact.exact_position)
        ),
    }


def view_field_names() -> frozenset[str]:
    """The view's field names, for the test that guards against a leaky field."""
    return frozenset(f.name for f in fields(PlayerView))
