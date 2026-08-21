from __future__ import annotations

import json
import random

from hypothesis import given, settings

from engine import Fire, Move, Ping, PlayerId, RunSilent, new_match, resolve
from perception import to_payload, view_for
from tests.strategies import actions, game_states, seeds


def wire_bytes(state, player: PlayerId, seed: int) -> str:
    view = view_for(state, player, random.Random(seed), phase="RESOLVED")
    return json.dumps(to_payload(view), sort_keys=True)


@settings(max_examples=1000, deadline=None)
@given(state=game_states(), action_p1=actions, action_p2=actions, seed=seeds)
def test_the_same_seed_produces_byte_identical_output(
    state, action_p1, action_p2, seed: int
) -> None:
    first_state, first_events = resolve(state, action_p1, action_p2, random.Random(seed))
    second_state, second_events = resolve(
        state, action_p1, action_p2, random.Random(seed)
    )

    assert first_state == second_state
    assert first_events == second_events

    for player in (PlayerId.P1, PlayerId.P2):
        assert wire_bytes(first_state, player, seed) == wire_bytes(
            second_state, player, seed
        )


def test_a_whole_match_replays_identically() -> None:
    def play(seed: int) -> list[str]:
        rng = random.Random(seed)
        state = new_match(seed=seed)
        transcript: list[str] = []
        choices = [RunSilent(), Ping(), Move("NE"), Move("SW"), Fire((12, 12))]

        for _ in range(20):
            state, _ = resolve(
                state, rng.choice(choices), rng.choice(choices), rng
            )
            transcript.append(wire_bytes(state, PlayerId.P1, seed))
            transcript.append(wire_bytes(state, PlayerId.P2, seed))
        return transcript

    assert play(4242) == play(4242)


def test_a_different_seed_produces_a_different_bearing() -> None:
    state = new_match(seed=5)
    resolved, _ = resolve(state, RunSilent(), Move("N"), random.Random(0))

    bearings = set()
    for seed in range(50):
        view = view_for(resolved, PlayerId.P1, random.Random(seed))
        bearings.update(
            contact.bearing_deg
            for contact in view.contacts
            if contact.bearing_deg is not None
        )

    assert len(bearings) > 1, "every seed produced the same bearing"


def test_the_seed_never_appears_in_a_players_view() -> None:
    state = new_match(seed=987654321)
    resolved, _ = resolve(state, Ping(), Move("N"), random.Random(1))

    for player in (PlayerId.P1, PlayerId.P2):
        body = json.dumps(to_payload(view_for(resolved, player, random.Random(1))))
        assert "987654321" not in body
        assert "rng_seed" not in body
