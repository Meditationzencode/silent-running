from __future__ import annotations

from engine import Action, Fire, Move
from perception import PlayerView

from ai.base import Bot, random_cell, random_direction


class Drifter(Bot):
    """Level 1. Moves and fires at random, never pings, ignores every contact."""

    level = 1
    name = "Drifter"
    FIRE_CHANCE = 0.25

    def choose_action(self, view: PlayerView) -> Action:
        if self.rng.random() < self.FIRE_CHANCE:
            return Fire(random_cell(self.rng, self.config))
        return Move(random_direction(self.rng))
