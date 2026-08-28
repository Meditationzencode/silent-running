from __future__ import annotations

from engine import Action, Coord, Fire, Move, Ping, RunSilent
from perception import PlayerView

from ai.tracker import Tracker


class Hunter(Tracker):
    """Level 4. Aims where a dodge would land, and moves off the cell it just lit up.

    Three changes on top of Tracker, all about the round it cannot see yet.

    It scores a shot against the cells the enemy could *reach*, not the ones
    they were last in. That is the honest hit probability - a Move carries a
    ship two cells and a blast reaches one - so where Tracker fires confidently
    at a pinned target and misses the moment that target steps aside, Hunter
    either finds a blast covering several escape squares or holds fire.

    It dodges the round after its own ping. A ping buys their exact cell and
    sells yours, and the standing retaliation is a torpedo on the cell you
    pinged from. Tracker stands there and shoots; Hunter steps aside first and
    takes the shot a round later, off the bearing their return fire gives away.

    And it is quieter: with the board wide open it listens rather than
    advertising a bearing for nothing.
    """

    level = 4
    name = "Hunter"
    FIRE_QUALITY = 0.16
    PING_BELIEF_SIZE = 140
    PING_RANGE_FRACTION = 0.9
    SWEEP_AFTER_QUIET_ROUNDS = 6
    APPROACH_BELIEF_SIZE = 150
    STAY_CHANCE = 0.55

    def decide(self, view: PlayerView, own: Coord, just_pinged: bool) -> Action:
        if just_pinged:
            return Move(self.away_from(own, self.belief.centroid()))

        threat = self.pinged_by(view)
        if threat is not None:
            return Move(self.away_from(own, threat))

        target, quality = self.aim()
        if quality >= self.FIRE_QUALITY:
            return Fire(target)

        estimate = self.belief.centroid()
        if self.should_ping(own, estimate):
            return Ping()

        if self.belief.size <= self.APPROACH_BELIEF_SIZE:
            return Move(self.toward(own, estimate))
        return RunSilent()

    def aim(self) -> tuple[Coord, float]:
        """Score the shot against where they will be next round, not where they are."""
        return self.belief.best_shot(self.belief.dodge_weights(self.STAY_CHANCE))

    def pinged_by(self, view: PlayerView) -> Coord | None:
        """Their cell, if they pinged - which also means they now hold ours."""
        for contact in view.contacts:
            if contact.kind == "PING_DETECTED" and contact.exact_position is not None:
                return contact.exact_position
        return None
