"""Round resolution — the fixed order that makes a simultaneous round fair.

Both captains commit in secret and the server resolves both at once, so there is
no first-mover advantage to exploit. What makes that *well-defined* rather than
merely simultaneous is the order in design §2.5, applied identically to both
players every round:

    a. movement    — both Moves apply, clamped to the grid; positions are final
    b. emissions   — each ship's signature is recorded at its POST-move position
    c. torpedoes   — every Fire detonates against those post-move positions, at
                     the same instant, so neither shot pre-empts the other
    d. detection   — contacts are computed from the other side's emissions

Two consequences fall straight out of that ordering and are worth stating
because they are the game's most-felt rules. Movement before detonation means a
ship that Moves off a targeted cell survives: the torpedo goes off on empty
space. And simultaneous detonation means a dying ship's torpedo still arrives —
mutual destruction is a draw, not a win for whoever was checked first.

Step (d) is a *hook* here, not an implementation: this module records emissions
and hands them back in RoundEvents. ``perception`` turns them into noised
contacts in phase 2. The engine deliberately owns no sensor maths.
"""

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
"""What each action broadcasts. RunSilent is absent — that is the whole point."""


def resolve(
    state: GameState,
    action_p1: Action,
    action_p2: Action,
    rng: random.Random,
) -> tuple[GameState, RoundEvents]:
    """Resolve one simultaneous round; return the new state and what happened.

    Pure: it reads ``state``, mutates nothing, and returns a fresh ``GameState``.
    Calling it twice with equal arguments produces equal results.

    ``rng`` is threaded through per design §4.1 even though nothing in
    *resolution* is currently random — movement, blast geometry and win checking
    are all deterministic. It stays in the signature because the seeded-PRNG
    contract belongs to the whole engine boundary, and because the alternative
    (adding it later) would be a breaking change to every caller at the exact
    moment a rule first needs randomness. The server owns the live Random; the
    seed it started from never leaves the server.

    Raises:
        InvalidAction: if either action is malformed or names an illegal target.
        ValueError: if the match has already ended.
    """
    if state.outcome is not Outcome.ONGOING:
        raise ValueError(f"cannot resolve a match that has ended ({state.outcome})")

    actions: Mapping[PlayerId, Action] = {
        PlayerId.P1: action_p1,
        PlayerId.P2: action_p2,
    }
    for action in actions.values():
        validate_action(action, state.config)

    # (a) Movement — both at once, clamped. Positions are final from here on.
    positions: dict[PlayerId, Coord] = {
        player: _move(state.ships[player].position, action, state.config)
        for player, action in actions.items()
    }

    # (b) Emissions — recorded at the post-movement position, so a ship cannot
    #     leave its signature at the cell it just vacated.
    emissions = tuple(
        Emission(source=player, kind=kind, position=positions[player])
        for player, action in actions.items()
        if (kind := _EMISSION_BY_ACTION.get(type(action))) is not None
    )

    # (c) Torpedoes — every Fire is resolved against the post-move positions
    #     before any damage is applied, so both shots land in the same instant.
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

    next_round = state.round + 1
    new_state = replace(
        state,
        ships=new_ships,
        round=next_round,
        outcome=_outcome(new_ships, next_round, state.config),
    )

    # (d) Detection hook — the raw emissions go back to the caller; perception
    #     decides who was close enough to hear what, and how badly to blur it.
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
    return new_state, events


def _move(position: Coord, action: Action, config: GameConfig) -> Coord:
    """Apply a Move, or leave the ship where it is.

    A Move always travels the full ``move_distance``; the action carries only a
    direction, so "up to 2 cells" in the design refers to clamping at the wall,
    not to a distance the captain chooses.
    """
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
    """Work out who a blast at ``target`` catches.

    Chebyshev distance, so ``blast_radius`` 1 is exactly the 3x3 footprint.

    The firer is excluded from their own blast. The spec never models
    self-damage: every win condition in PRD §2 is phrased about *the enemy*
    ("the enemy ship's true cell falls inside that blast"), and v1 explicitly
    does not model collision either. Adding self-damage would be inventing a
    mechanic, so this is the conservative reading — and it is one line to flip.
    """
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
    """Move the ship and subtract any hits. Hull floors at 0; 0 hull is death."""
    hull = max(0, ship.hull - hits)
    return ShipState(position=position, hull=hull, alive=hull > 0)


def _outcome(
    ships: Mapping[PlayerId, ShipState], next_round: int, config: GameConfig
) -> Outcome:
    """Decide how the match stands after a round has been applied.

    Mutual destruction is checked first, so a round in which both ships die is a
    draw rather than a win for whichever player happens to be tested first.

    The round cap is checked last and only with both ships alive: a kill on the
    final round is a win, not a draw. ``next_round > round_cap`` means exactly
    ``round_cap`` rounds get played — round 50 is resolved, and the match ends
    when the counter would move to 51.
    """
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
