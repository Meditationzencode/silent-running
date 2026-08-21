"""``view_for`` — the single doorway between the truth and a player.

Every byte a player ever receives about the match passes through this function.
That is the design: not "be careful not to leak", but "there is one place where
leaking would have to happen, and it is forty lines long and fully tested".
"""

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
    """Build the fogged view one player is allowed to see.

    Pure and deterministic given ``rng``: the same state, player and seed always
    produce an identical view, which is what makes the leak proof reproducible.

    ``phase`` and ``opponent_status`` are keyword arguments with defaults because
    they are not perceptual facts — the server is the only thing that knows
    whether both actions are in or whether the opponent has stopped polling. They
    live on the view because PRD §6 puts them in the response body, and they are
    keyword-only so that a caller must name what it is asserting.
    """
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
    """Everything this player detected in the round that just resolved.

    Two independent sources, and the distinction matters: what the *enemy*
    broadcast (which the enemy chose to risk), and what this player's *own* ping
    brought back (which this player chose to pay for). A round can produce both —
    ping into an enemy ping and you each learn the other's exact cell.

    Contacts are built in a fixed order — enemy emission first, then your own
    fix — so the same inputs always serialize to the same bytes.
    """
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
            # Loud, and never range-gated: the pinger always gives itself away.
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
    """Translate the engine's absolute outcome into this player's seat."""
    if outcome is Outcome.ONGOING:
        return "ONGOING"
    if outcome is Outcome.DRAW:
        return "DRAW"

    winner = PlayerId.P1 if outcome is Outcome.P1_WINS else PlayerId.P2
    return "WIN" if winner is player else "LOSS"
