from __future__ import annotations

from engine import Action, InvalidAction, PlayerId, RunSilent, resolve, validate_action
from perception import view_for
from server.store import MatchRecord, RoundRecord


def bot_action(record: MatchRecord) -> Action:
    """Ask the seated bot for its move, from the same fogged view a human gets.

    Built from the state *before* the human's action is applied, so the bot is
    choosing blind against a simultaneous opponent exactly as the rules intend.

    An illegal answer is replaced with Run Silent rather than failing the
    human's request: the same safe default a player gets for missing a turn, and
    the alternative is a bot bug reading as a 400 on someone else's good action.
    """
    view = view_for(
        record.state,
        PlayerId.P2,
        record.view_rng(PlayerId.P2),
        phase="AWAITING_ACTIONS",
    )
    action = record.opponent.choose_action(view)  # type: ignore[union-attr]
    try:
        validate_action(action, record.state.config)
    except InvalidAction:
        return RunSilent()
    return action


def fill_bot_seat(record: MatchRecord) -> None:
    """Give the bot its move for this round, if a bot holds the second seat."""
    if record.opponent is not None and PlayerId.P2 not in record.pending:
        record.pending[PlayerId.P2] = bot_action(record)


def resolve_round(record: MatchRecord, now: float) -> None:
    """Resolve the round both players have now committed to, and open the next."""
    actions = dict(record.pending)
    new_state, events = resolve(
        record.state,
        actions[PlayerId.P1],
        actions[PlayerId.P2],
        record.resolve_rng(),
    )
    record.history.append(
        RoundRecord(
            round=events.round,
            actions=actions,
            events=events,
            ships_after=dict(new_state.ships),
        )
    )
    record.state = new_state
    record.pending.clear()
    record.round_opened_at = now
