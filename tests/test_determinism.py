"""Determinism — the property every other test in the suite rests on.

Design §7 item 2. If the same seed did not produce the same match, no failure
could be reproduced, the leak invariant could not be trusted (a leak might
appear only on the run nobody watched), and a match could not be replayed for
review.

"Byte-identical" is meant literally here: the comparison is on the serialized
JSON, not on Python objects, because JSON is what a client actually receives.
"""

from __future__ import annotations

import json
import random

from hypothesis import given, settings

from engine import Fire, Move, Ping, PlayerId, RunSilent, new_match, resolve
from perception import to_payload, view_for
from tests.strategies import actions, game_states, seeds


def wire_bytes(state, player: PlayerId, seed: int) -> str:
    """Exactly what the endpoint would send, as a stable string."""
    view = view_for(state, player, random.Random(seed), phase="RESOLVED")
    return json.dumps(to_payload(view), sort_keys=True)


@settings(max_examples=1000, deadline=None)
@given(state=game_states(), action_p1=actions, action_p2=actions, seed=seeds)
def test_the_same_seed_produces_byte_identical_output(
    state, action_p1, action_p2, seed: int
) -> None:
    """resolve twice, view twice, and compare the actual response bodies."""
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
    """Round-by-round determinism compounds: the entire match is reproducible.

    Stronger than the single-round property, because it would also catch state
    that leaks between rounds — a cached bearing, a module-level counter, a
    mutable default — none of which shows up when you only ever resolve once.
    """

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
    """The other half of the claim: the noise is real, not a fixed offset.

    A degradation layer that returned the true bearing every time would satisfy
    every determinism assertion above. This is what stops that from passing.
    """
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
    """The seed is the key to the noise; shipping it would undo the whole model.

    A client holding the seed could replay the PRNG, subtract the error off each
    bearing and recover the truth — the fog would still be applied and would no
    longer hide anything.
    """
    state = new_match(seed=987654321)
    resolved, _ = resolve(state, Ping(), Move("N"), random.Random(1))

    for player in (PlayerId.P1, PlayerId.P2):
        body = json.dumps(to_payload(view_for(resolved, player, random.Random(1))))
        assert "987654321" not in body
        assert "rng_seed" not in body
