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
    new_state, _ = resolve(state, action_p1, action_p2, random.Random(seed))
    pingers = {
        emission.source
        for emission in new_state.last_events.emissions
        if emission.kind == "PING"
    }

    for player in (PlayerId.P1, PlayerId.P2):
        view = view_for(new_state, player, random.Random(seed), phase="RESOLVED")

        payload = json.loads(json.dumps(to_payload(view)))

        own = new_state.ships[player].position
        enemy = new_state.ships[player.other].position
        granted = {
            contact.exact_position
            for contact in view.contacts
            if contact.kind in EXACT_KINDS
        }

        for contact in view.contacts:
            if contact.kind == "PING_DETECTED":
                assert player.other in pingers, "a fix from a ping nobody made"
            if contact.kind == "ACTIVE_FIX":
                assert player in pingers, "an active fix without having pinged"
                assert euclidean_distance(own, enemy) <= DEFAULT.ping_range, (
                    "an active fix on an enemy outside PING_RANGE"
                )

        assert set(coordinates_in(payload)) <= {own} | granted

        if enemy not in granted and enemy != own:
            assert enemy not in coordinates_in(payload), (
                f"leaked enemy cell {enemy} in {payload}"
            )

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
    new_state, _ = resolve(state, action_p1, action_p2, random.Random(seed))

    for player in (PlayerId.P1, PlayerId.P2):
        view = view_for(new_state, player, random.Random(seed))
        for contact in view.contacts:
            if contact.bearing_deg is not None:
                assert 0.0 <= contact.bearing_deg < 360.0
                assert contact.bearing_deg == round(contact.bearing_deg, 1)


def test_the_view_has_no_field_that_could_describe_the_enemy() -> None:
    assert view_field_names().isdisjoint(FORBIDDEN_FIELD_NAMES)


def test_the_payload_has_exactly_the_keys_the_prd_specifies() -> None:
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
