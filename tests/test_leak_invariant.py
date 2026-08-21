"""The leak invariant — the test this whole project exists to pass.

Design §7 item 1: generate thousands of states and action pairs, build both
players' views, serialize each exactly as the response body would be, and assert
the enemy's true cell never appears unless the sensor rules legitimately granted
it.

Two additions to the sketch in the design doc, both necessary:

**The sketch is self-justifying as written.** It asks whether a legitimate fix
exists and, if so, permits the exact cell. A broken ``view_for`` that attached an
ACTIVE_FIX to *every* view would satisfy that and leak on every round. So this
version also checks the converse — that each granted fix is one the round
actually earned: a PING_DETECTED only when the enemy really pinged, an
ACTIVE_FIX only when *you* pinged and the enemy really was inside PING_RANGE.

**Sharing a cell is not a leak.** Design §2.5 allows both ships to occupy one
cell. When they do, the enemy's true cell is also *your* cell, which your own
view is entitled to state. The invariant is about the enemy's position reaching
you as new information, not about a coordinate never coincidentally matching.
"""

from __future__ import annotations

import json
import random
from typing import Any

from hypothesis import given, settings

from config import DEFAULT
from engine import GameState, Move, Ping, PlayerId, ShipState, resolve
from engine.geometry import euclidean_distance
from perception import FORBIDDEN_FIELD_NAMES, to_payload, view_field_names, view_for
from tests.strategies import actions, coordinates_in, game_states, seeds

EXACT_KINDS = ("ACTIVE_FIX", "PING_DETECTED")


@settings(max_examples=2000, deadline=None)
@given(state=game_states(), action_p1=actions, action_p2=actions, seed=seeds)
def test_a_view_never_leaks_the_enemys_position(
    state: GameState, action_p1: Any, action_p2: Any, seed: int
) -> None:
    """Truth never reaches the wire unless the sensor rules put it there."""
    new_state, _ = resolve(state, action_p1, action_p2, random.Random(seed))
    pingers = {
        emission.source
        for emission in new_state.last_events.emissions  # type: ignore[union-attr]
        if emission.kind == "PING"
    }

    for player in (PlayerId.P1, PlayerId.P2):
        view = view_for(new_state, player, random.Random(seed), phase="RESOLVED")

        # Exactly what the endpoint would put on the wire, round-tripped through
        # JSON so the assertion runs against the same shapes a client receives.
        payload = json.loads(json.dumps(to_payload(view)))

        own = new_state.ships[player].position
        enemy = new_state.ships[player.other].position
        granted = {
            contact.exact_position
            for contact in view.contacts
            if contact.kind in EXACT_KINDS
        }

        # 1. Every fix in the view was actually earned this round. Without this,
        #    a view that always attached an ACTIVE_FIX would pass check 2.
        for contact in view.contacts:
            if contact.kind == "PING_DETECTED":
                assert player.other in pingers, "a fix from a ping nobody made"
            if contact.kind == "ACTIVE_FIX":
                assert player in pingers, "an active fix without having pinged"
                assert euclidean_distance(own, enemy) <= DEFAULT.ping_range, (
                    "an active fix on an enemy outside PING_RANGE"
                )

        # 2. The only coordinates on the wire are your own cell and earned fixes.
        assert set(coordinates_in(payload)) <= {own} | granted

        # 3. The invariant, stated the way the design doc states it.
        if enemy not in granted and enemy != own:
            assert enemy not in coordinates_in(payload), (
                f"leaked enemy cell {enemy} in {payload}"
            )

        # 4. A degraded contact is structurally incapable of carrying a cell.
        for contact in view.contacts:
            if contact.kind in ("PASSIVE_BEARING", "LAUNCH_DETECTED"):
                assert contact.exact_position is None
                assert contact.bearing_deg is not None
                assert contact.range_bucket is not None


@settings(max_examples=500, deadline=None)
@given(state=game_states(), action_p1=actions, action_p2=actions, seed=seeds)
def test_a_reported_bearing_is_always_a_legal_compass_value(
    state: GameState, action_p1: Any, action_p2: Any, seed: int
) -> None:
    """Every bearing is in [0, 360) at the stated precision.

    Gaussian noise is unbounded, so a true bearing near due east plus a negative
    draw wraps below zero and a positive one wraps past 360. Both must come back
    as a bearing a client can plot without special-casing.

    This found a real bug on its first run: wrapping before rounding let 359.97
    round up to 360.0, a value no compass has.
    """
    new_state, _ = resolve(state, action_p1, action_p2, random.Random(seed))

    for player in (PlayerId.P1, PlayerId.P2):
        view = view_for(new_state, player, random.Random(seed))
        for contact in view.contacts:
            if contact.bearing_deg is not None:
                assert 0.0 <= contact.bearing_deg < 360.0
                assert contact.bearing_deg == round(contact.bearing_deg, 1)


def test_the_view_has_no_field_that_could_describe_the_enemy() -> None:
    """A guardrail against "just one more field to make the client easier"."""
    assert view_field_names().isdisjoint(FORBIDDEN_FIELD_NAMES)


def test_the_payload_has_exactly_the_keys_the_prd_specifies() -> None:
    """A new key is a new way to leak; it should have to be added deliberately."""
    state = GameState(
        ships={
            PlayerId.P1: ShipState((10, 10), 1),
            PlayerId.P2: ShipState((16, 13), 1),
        },
        round=1,
        rng_seed=0,
    )
    new_state, _ = resolve(state, Ping(), Move("W"), random.Random(0))
    payload = to_payload(view_for(new_state, PlayerId.P1, random.Random(0)))

    assert set(payload) == {
        "round",
        "phase",
        "your_ship",
        "contacts",
        "last_result",
        "opponent_status",
        "outcome",
    }
    assert set(payload["your_ship"]) == {"position", "hull", "alive"}
    assert set(payload["last_result"]) == {"you_were_hit", "you_hit_enemy"}
    assert set(payload["contacts"][0]) == {
        "kind",
        "bearing_deg",
        "range_bucket",
        "exact_position",
    }
