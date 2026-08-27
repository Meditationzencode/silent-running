from __future__ import annotations

import random

from engine import Contact, GameState, Outcome, PlayerId
from perception.models import OpponentStatus, Phase, PlayerOutcome, PlayerView
from perception.sensors import active_fix, passive_contact, ping_detected


def view_for(
    state: GameState,
    player: PlayerId,
    rng: random.Random,
    *,
    phase: Phase = "AWAITING_ACTIONS",
    opponent_status: OpponentStatus = "CONNECTED",
) -> PlayerView:
    """The fogged view one player may see. The only doorway between truth and a player."""
    return PlayerView(
        round=state.round,
        phase=phase,
        your_ship=state.ships[player],
        contacts=_contacts_for(state, player, rng),
        last_result=(
            None if state.last_events is None else state.last_events.results[player]
        ),
        opponent_status=opponent_status,
        outcome=_outcome_for(state.outcome, player),
    )


def _contacts_for(
    state: GameState, player: PlayerId, rng: random.Random
) -> tuple[Contact, ...]:
    events = state.last_events
    if events is None:
        return ()

    listener = state.ships[player].position
    enemy = player.other
    contacts: list[Contact] = []

    for emission in events.emissions:
        if emission.source is not enemy:
            continue
        if emission.kind == "PING":
            contacts.append(ping_detected(emission.position))
        else:
            heard = passive_contact(
                listener, emission.position, emission.kind, rng, state.config
            )
            if heard is not None:
                contacts.append(heard)

    if any(e.source is player and e.kind == "PING" for e in events.emissions):
        fix = active_fix(listener, state.ships[enemy].position, state.config)
        if fix is not None:
            contacts.append(fix)

    return tuple(contacts)


def _outcome_for(outcome: Outcome, player: PlayerId) -> PlayerOutcome:
    if outcome is Outcome.ONGOING:
        return "ONGOING"
    if outcome is Outcome.DRAW:
        return "DRAW"

    winner = PlayerId.P1 if outcome is Outcome.P1_WINS else PlayerId.P2
    return "WIN" if winner is player else "LOSS"
