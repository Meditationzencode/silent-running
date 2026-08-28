"""AI opponents. Headless clients: a PlayerView in, an Action out, no GameState."""

from __future__ import annotations

import random

from config import DEFAULT, GameConfig

from ai.base import Bot
from ai.belief import Belief
from ai.drifter import Drifter
from ai.ghost import Ghost
from ai.hunter import Hunter
from ai.reactor import Reactor
from ai.tracker import Tracker

LEVELS: dict[int, type[Bot]] = {
    1: Drifter,
    2: Reactor,
    3: Tracker,
    4: Hunter,
    5: Ghost,
}


def make_bot(
    level: int, rng: random.Random | None = None, config: GameConfig = DEFAULT
) -> Bot:
    """Build the bot for a difficulty level, 1 (Drifter) to 5 (Ghost)."""
    if level not in LEVELS:
        raise ValueError(f"no such level {level!r}; expected one of {sorted(LEVELS)}")
    return LEVELS[level](rng, config)


__all__ = [
    "LEVELS",
    "Belief",
    "Bot",
    "Drifter",
    "Ghost",
    "Hunter",
    "Reactor",
    "Tracker",
    "make_bot",
]
