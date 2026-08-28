from __future__ import annotations

import random
from dataclasses import dataclass

from ai.base import Bot
from config import DEFAULT, GameConfig
from engine import Action, Outcome, PlayerId, new_match, resolve
from perception import view_for


@dataclass(frozen=True)
class MatchOutcome:
    outcome: Outcome
    rounds: int
    actions: list[tuple[PlayerId, Action]]


def play_match(
    bot_p1: Bot, bot_p2: Bot, seed: int, config: GameConfig = DEFAULT
) -> MatchOutcome:
    """Run one bot-versus-bot match, handing each side only its own PlayerView.

    Lives in test support rather than in ai/ because it holds the GameState. The
    bots never receive it - each is given exactly what an HTTP client would get.
    """
    state = new_match(seed=seed, config=config)
    bots = {PlayerId.P1: bot_p1, PlayerId.P2: bot_p2}
    submitted: list[tuple[PlayerId, Action]] = []
    rounds = 0

    while state.outcome is Outcome.ONGOING:
        chosen: dict[PlayerId, Action] = {}
        for player, bot in bots.items():
            view = view_for(
                state,
                player,
                random.Random(f"{seed}:{state.round}:{player.value}"),
                phase="RESOLVED",
            )
            action = bot.choose_action(view)
            chosen[player] = action
            submitted.append((player, action))

        state, _ = resolve(
            state,
            chosen[PlayerId.P1],
            chosen[PlayerId.P2],
            random.Random(f"{seed}:{state.round}"),
        )
        rounds += 1

    return MatchOutcome(outcome=state.outcome, rounds=rounds, actions=submitted)
