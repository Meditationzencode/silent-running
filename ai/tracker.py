from __future__ import annotations

import random

from config import DEFAULT, GameConfig
from engine import Action, Coord, Fire, Move, Ping, RunSilent
from engine.geometry import euclidean_distance
from perception import PlayerView, true_bearing_deg

from ai.base import Bot, bearing_to_direction
from ai.belief import Belief


class Tracker(Bot):
    """Level 3. Holds a belief over enemy cells and narrows it as bearings arrive.

    The first level that accumulates evidence rather than reacting to it, and
    the first that decides whether a shot is worth taking: it fires when the
    best available blast would cover enough of what it still believes, instead
    of whenever the belief happens to have shrunk below some size.

    It also breaks a stalemate. Two silent ships never find each other, so after
    enough quiet rounds it sweeps with a ping and accepts being heard.

    Two blind spots, and they are what levels 4 and 5 are built on. It aims at
    where the enemy is rather than where they can be a round from now. And it
    fires the moment after its own ping, from the cell that ping just
    advertised.
    """

    level = 3
    name = "Tracker"
    FIRE_QUALITY = 0.14
    PING_BELIEF_SIZE = 200
    PING_RANGE_FRACTION = 0.8
    SWEEP_AFTER_QUIET_ROUNDS = 7

    def __init__(
        self, rng: random.Random | None = None, config: GameConfig = DEFAULT
    ) -> None:
        super().__init__(rng, config)
        self.belief = Belief(self.config)
        self.quiet_rounds = 0
        self.pinged_last_round = False

    def choose_action(self, view: PlayerView) -> Action:
        self.belief.advance(view)
        own = view.your_ship.position
        self.quiet_rounds = 0 if view.contacts else self.quiet_rounds + 1
        just_pinged, self.pinged_last_round = self.pinged_last_round, False

        action = self.decide(view, own, just_pinged)
        self.pinged_last_round = isinstance(action, Ping)
        return action

    def decide(self, view: PlayerView, own: Coord, just_pinged: bool) -> Action:
        target, quality = self.aim()
        if quality >= self.FIRE_QUALITY:
            return Fire(target)

        estimate = self.belief.centroid()
        if self.should_ping(own, estimate):
            return Ping()

        # Always closing, even with no lead worth the name. Staying quiet is
        # strong here, and not knowing that is what keeps this level below the
        # two above it.
        return Move(self.toward(own, estimate))

    def aim(self) -> tuple[Coord, float]:
        """Where to shoot and how good the shot is, against the current belief."""
        return self.belief.best_shot()

    def should_ping(self, own: Coord, estimate: Coord) -> bool:
        """Spend a ping when it should land, or when silence has stalled the match."""
        if self.quiet_rounds >= self.SWEEP_AFTER_QUIET_ROUNDS:
            return True
        if self.belief.size > self.PING_BELIEF_SIZE:
            return False
        reach = self.config.ping_range * self.PING_RANGE_FRACTION
        return euclidean_distance(own, estimate) <= reach

    def toward(self, own: Coord, target: Coord) -> str:
        """The compass direction that closes on a cell."""
        return bearing_to_direction(true_bearing_deg(own, target))

    def away_from(self, own: Coord, threat: Coord) -> str:
        """The compass direction that opens the range."""
        if own == threat:
            return bearing_to_direction(self.rng.random() * 360.0)
        return bearing_to_direction(true_bearing_deg(threat, own))
