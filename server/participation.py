from __future__ import annotations

from config import DEFAULT, GameConfig
from engine import Outcome, PlayerId, RunSilent, resign, void
from perception import OpponentStatus
from server.rounds import fill_bot_seat, resolve_round
from server.store import MatchRecord

SEATS = (PlayerId.P1, PlayerId.P2)


def is_bot(record: MatchRecord, player: PlayerId) -> bool:
    """A bot never goes quiet and never runs out of turns."""
    return record.opponent is not None and player is PlayerId.P2


def touch(record: MatchRecord, player: PlayerId, now: float) -> None:
    """Stamp liveness. Every authenticated request counts, poll or action."""
    record.last_seen[player] = now


def status_of(
    record: MatchRecord,
    player: PlayerId,
    now: float,
    config: GameConfig = DEFAULT,
) -> OpponentStatus:
    """How present a player is, judged only by when they last said anything."""
    if is_bot(record, player) or player not in record.last_seen:
        return "CONNECTED"

    silence = now - record.last_seen[player]
    if silence >= config.abandon_after_s:
        return "ABANDONED"
    if silence >= config.grace_window_s:
        return "DISCONNECTED_GRACE"
    return "CONNECTED"


def advance(record: MatchRecord, now: float, config: GameConfig = DEFAULT) -> None:
    """Apply everything the clock has made true since anyone last asked.

    There is no scheduler. Every authenticated request runs this first, which
    works precisely because the clients poll: the polling that keeps a player
    visible is the same traffic that notices the other one has gone.

    Call this *before* stamping the caller's own liveness. A player returning
    after the abandon threshold has already lost - the match ended at the
    threshold, and the only reason nobody had recorded it yet is that nobody had
    asked.
    """
    if record.state.outcome is not Outcome.ONGOING or not record.is_full:
        return

    _apply_abandonment(record, now, config)
    if record.state.outcome is not Outcome.ONGOING:
        return
    _apply_turn_timeout(record, now, config)


def _apply_abandonment(
    record: MatchRecord, now: float, config: GameConfig
) -> None:
    gone = [seat for seat in SEATS if status_of(record, seat, now, config) == "ABANDONED"]
    if len(gone) == len(SEATS):
        record.state = void(record.state)
    elif gone:
        record.state = resign(record.state, gone[0])


def _apply_turn_timeout(
    record: MatchRecord, now: float, config: GameConfig
) -> None:
    if now - record.round_opened_at < config.turn_timeout_s:
        return

    missed = [
        seat
        for seat in SEATS
        if seat not in record.pending and not is_bot(record, seat)
    ]
    if not missed:
        return

    # Run Silent is the safe substitution: it emits nothing, so a player who
    # misses a turn cannot be made to give away a position by failing to act.
    for seat in missed:
        record.pending[seat] = RunSilent()
        record.timeouts[seat] += 1

    fill_bot_seat(record)
    if len(record.pending) == len(SEATS):
        resolve_round(record, now)

    _apply_forfeits(record, config)


def _apply_forfeits(record: MatchRecord, config: GameConfig) -> None:
    if record.state.outcome is not Outcome.ONGOING:
        return

    out = [
        seat
        for seat in SEATS
        if record.timeouts[seat] >= config.max_consecutive_timeouts
    ]
    if len(out) == len(SEATS):
        record.state = void(record.state)
    elif out:
        record.state = resign(record.state, out[0])
