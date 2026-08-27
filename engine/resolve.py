from __future__ import annotations

import random
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace

from config import GameConfig
from engine.geometry import chebyshev_distance, clamp_to_grid
from engine.models import (
    DIRECTION_VECTORS,
    Action,
    Coord,
    Detonation,
    Emission,
    EmissionKind,
    Fire,
    GameState,
    Move,
    Outcome,
    Ping,
    PlayerId,
    RoundEvents,
    RoundResult,
    ShipState,
)
from engine.validation import validate_action

_EMISSION_BY_ACTION: Mapping[type[Action], EmissionKind] = {
    Move: "HEAT",
    Fire: "LAUNCH",
    Ping: "PING",
}


def resolve(
    state: GameState,
    action_p1: Action,
    action_p2: Action,
    rng: random.Random,
) -> tuple[GameState, RoundEvents]:
    if state.outcome is not Outcome.ONGOING:
        raise ValueError(f"cannot resolve a match that has ended ({state.outcome})")

    actions: Mapping[PlayerId, Action] = {
        PlayerId.P1: action_p1,
        PlayerId.P2: action_p2,
    }
    for action in actions.values():
        validate_action(action, state.config)

    positions: dict[PlayerId, Coord] = {
        player: _move(state.ships[player].position, action, state.config)
        for player, action in actions.items()
    }

    emissions = tuple(
        Emission(source=player, kind=kind, position=positions[player])
        for player, action in actions.items()
        if (kind := _EMISSION_BY_ACTION.get(type(action))) is not None
    )

    detonations = tuple(
        _detonate(player, action.target, positions, state.config)
        for player, action in actions.items()
        if isinstance(action, Fire)
    )
    damage: Counter[PlayerId] = Counter()
    for detonation in detonations:
        damage.update(detonation.caught)

    new_ships = {
        player: _apply_damage(ship, positions[player], damage[player])
        for player, ship in state.ships.items()
    }

    events = RoundEvents(
        round=state.round,
        emissions=emissions,
        detonations=detonations,
        results={
            player: RoundResult(
                you_were_hit=damage[player] > 0,
                you_hit_enemy=any(
                    d.source is player and player.other in d.caught
                    for d in detonations
                ),
            )
            for player in actions
        },
    )

    next_round = state.round + 1
    new_state = replace(
        state,
        ships=new_ships,
        round=next_round,
        outcome=_outcome(new_ships, next_round, state.config),
        last_events=events,
    )
    return new_state, events


def resign(state: GameState, player: PlayerId) -> GameState:
    if state.outcome is not Outcome.ONGOING:
        raise ValueError(f"cannot resign a match that has ended ({state.outcome})")

    return replace(
        state,
        outcome=Outcome.P2_WINS if player is PlayerId.P1 else Outcome.P1_WINS,
    )


def _move(position: Coord, action: Action, config: GameConfig) -> Coord:
    if not isinstance(action, Move):
        return position

    dx, dy = DIRECTION_VECTORS[action.direction]
    return (
        clamp_to_grid(position[0] + dx * config.move_distance, config.grid_size),
        clamp_to_grid(position[1] + dy * config.move_distance, config.grid_size),
    )


def _detonate(
    source: PlayerId,
    target: Coord,
    positions: Mapping[PlayerId, Coord],
    config: GameConfig,
) -> Detonation:
    return Detonation(
        source=source,
        target=target,
        caught=tuple(
            player
            for player, position in positions.items()
            if player is not source
            and chebyshev_distance(position, target) <= config.blast_radius
        ),
    )


def _apply_damage(ship: ShipState, position: Coord, hits: int) -> ShipState:
    hull = max(0, ship.hull - hits)
    return ShipState(position=position, hull=hull, alive=hull > 0)


def _outcome(
    ships: Mapping[PlayerId, ShipState], next_round: int, config: GameConfig
) -> Outcome:
    p1_alive = ships[PlayerId.P1].alive
    p2_alive = ships[PlayerId.P2].alive

    if not p1_alive and not p2_alive:
        return Outcome.DRAW
    if not p2_alive:
        return Outcome.P1_WINS
    if not p1_alive:
        return Outcome.P2_WINS
    if next_round > config.round_cap:
        return Outcome.DRAW
    return Outcome.ONGOING
