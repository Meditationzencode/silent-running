from __future__ import annotations

from engine import Action, Fire, Move, RunSilent
from perception import PlayerView, true_bearing_deg

from ai.base import (
    Bot,
    bearing_contact,
    bearing_to_direction,
    bucket_midpoint,
    exact_contact,
    project,
)


class Reactor(Bot):
    """Level 2. Silent until something is heard, then moves and fires that way.

    Keeps no memory between rounds: a bearing is acted on and forgotten, so it
    never triangulates. That is the whole difference between it and Tracker.
    """

    level = 2
    name = "Reactor"
    FIRE_CHANCE = 0.35

    def choose_action(self, view: PlayerView) -> Action:
        fix = exact_contact(view)
        if fix is not None and fix.exact_position is not None:
            # Loose even when handed a certainty: it shoots at an exact cell as
            # readily as it shoots at a guessed one, and otherwise just closes.
            if self.rng.random() < self.FIRE_CHANCE:
                return Fire(fix.exact_position)
            return Move(
                bearing_to_direction(
                    true_bearing_deg(view.your_ship.position, fix.exact_position)
                )
            )

        heard = bearing_contact(view)
        if heard is None or heard.bearing_deg is None or heard.range_bucket is None:
            return RunSilent()

        if self.rng.random() < self.FIRE_CHANCE:
            estimate = project(
                view.your_ship.position,
                heard.bearing_deg,
                bucket_midpoint(heard.range_bucket, self.config),
                self.config,
            )
            return Fire(estimate)
        return Move(bearing_to_direction(heard.bearing_deg))
