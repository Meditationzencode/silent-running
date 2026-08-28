from __future__ import annotations

from engine import DIRECTION_VECTORS, Action, Coord, Fire, Move, Ping, RunSilent
from engine.geometry import clamp_to_grid
from perception import PlayerView, true_bearing_deg

from ai.base import bearing_to_direction, random_direction
from ai.hunter import Hunter


class Ghost(Hunter):
    """Level 5. Hunter, plus the mind-game layer.

    Its edge is knowing what the round after a ping looks like from the other
    side. A ping hands over your exact cell, and a disciplined opponent answers
    by running rather than shooting - directly away from the only position it
    can be sure of, which is yours. So Ghost does not spend the round after its
    own ping getting clear. It drops a torpedo one step along that line of
    flight, where a single blast covers both the cell they are standing in and
    the cell they are running to.

    Being pinged is likewise an opportunity, not a threat: a PING_DETECTED
    carries the pinger's exact cell, and Hunter spends that gift fleeing.

    It also jinks, so an opponent modelling its approach as a straight line is
    aiming at a cell it never meant to occupy, and it will occasionally ping
    without meaning to commit - a ping is what a ship does when it is ready to
    kill, so an early one sells a false read on what happens next.
    """

    level = 5
    name = "Ghost"
    JINK_CHANCE = 0.3
    BAIT_CHANCE = 0.04
    AMBUSH_BELIEF_SIZE = 12
    AMBUSH_CHANCE = 0.65

    def decide(self, view: PlayerView, own: Coord, just_pinged: bool) -> Action:
        if just_pinged:
            # The ambush assumes they run. Against something that shoots back
            # instead, standing still to take the shot is how you die, so it is
            # a habit rather than a rule.
            if (
                self.belief.size <= self.AMBUSH_BELIEF_SIZE
                and self.rng.random() < self.AMBUSH_CHANCE
            ):
                return Fire(self.ambush(own, self.belief.centroid()))
            return Move(self.away_from(own, self.belief.centroid()))

        if self.pinged_by(view) is not None:
            return Fire(self.belief.best_blast(self.belief.dodge_weights(self.STAY_CHANCE)))

        target, quality = self.aim()
        if quality >= self.FIRE_QUALITY:
            return Fire(target)

        estimate = self.belief.centroid()
        if self.should_ping(own, estimate):
            return Ping()

        if self.belief.size <= self.APPROACH_BELIEF_SIZE:
            if self.rng.random() < self.BAIT_CHANCE:
                return Ping()
            if self.rng.random() < self.JINK_CHANCE:
                return Move(random_direction(self.rng))
            return Move(self.toward(own, estimate))
        return RunSilent()

    def ambush(self, own: Coord, enemy: Coord) -> Coord:
        """One step along their line of flight, so the blast covers both cells."""
        dx, dy = DIRECTION_VECTORS[bearing_to_direction(true_bearing_deg(own, enemy))]
        step = max(1, self.config.move_distance // 2)
        return (
            clamp_to_grid(enemy[0] + dx * step, self.config.grid_size),
            clamp_to_grid(enemy[1] + dy * step, self.config.grid_size),
        )
