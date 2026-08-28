from __future__ import annotations

import secrets
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from random import Random

from ai import Bot
from config import DEFAULT, GameConfig
from engine import Action, GameState, PlayerId, RoundEvents, ShipState, new_match

TOKEN_BYTES = 32
SEED_BITS = 64


@dataclass(frozen=True)
class RoundRecord:
    round: int
    actions: Mapping[PlayerId, Action]
    events: RoundEvents
    ships_after: Mapping[PlayerId, ShipState]


@dataclass
class MatchRecord:
    match_id: str
    state: GameState
    tokens: dict[str, PlayerId] = field(default_factory=dict)
    pending: dict[PlayerId, Action] = field(default_factory=dict)
    history: list[RoundRecord] = field(default_factory=list)
    opponent: Bot | None = None
    """A bot holding the P2 seat in a solo match. It gets a PlayerView like anyone."""

    last_seen: dict[PlayerId, float] = field(default_factory=dict)
    """When each player last made an authenticated request. Polling is the heartbeat."""

    timeouts: Counter[PlayerId] = field(default_factory=Counter)
    """Consecutive rounds missed. Reset by acting, not by merely being present."""

    round_opened_at: float = 0.0

    @property
    def is_full(self) -> bool:
        return len(self.seats_taken) >= 2

    @property
    def seats_taken(self) -> set[PlayerId]:
        """Seats that are spoken for, whether by a token or by a bot."""
        taken = set(self.tokens.values())
        if self.opponent is not None:
            taken.add(PlayerId.P2)
        return taken

    def seat(self, player: PlayerId) -> str:
        token = secrets.token_urlsafe(TOKEN_BYTES)
        self.tokens[token] = player
        return token

    def player_for(self, token: str) -> PlayerId | None:
        return self.tokens.get(token)

    def resolve_rng(self) -> Random:
        return Random(f"{self.state.rng_seed}:{self.state.round}")

    def view_rng(self, player: PlayerId) -> Random:
        """A stream derived per round, so a bearing does not change while you poll.

        Not a live rng: view_for draws noise on every call, so a shared stream
        would redraw on every GET and let a client average the fog away. Seeded
        with a string because Random falls back to hash() for other types, and
        string hashing is randomised per process.
        """
        return Random(f"{self.state.rng_seed}:{self.state.round}:{player.value}")


class MatchStore:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._matches: dict[str, MatchRecord] = {}
        self.clock = clock
        """Injectable so tests can move time without sleeping through a match."""

    def create(
        self, config: GameConfig = DEFAULT, opponent: Bot | None = None
    ) -> tuple[MatchRecord, str]:
        """Open a match. The id is the join code, so it must be unguessable."""
        match_id = secrets.token_urlsafe(TOKEN_BYTES)
        record = MatchRecord(
            match_id=match_id,
            state=new_match(seed=secrets.randbits(SEED_BITS), config=config),
            opponent=opponent,
            round_opened_at=self.clock(),
        )
        token = record.seat(PlayerId.P1)
        self._matches[match_id] = record
        return record, token

    def get(self, match_id: str) -> MatchRecord | None:
        return self._matches.get(match_id)

    def clear(self) -> None:
        self._matches.clear()
