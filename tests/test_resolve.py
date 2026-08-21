from __future__ import annotations

import random
from dataclasses import replace

import pytest

from config import DEFAULT, GameConfig
from engine import (
    Coord,
    Fire,
    GameState,
    Move,
    Outcome,
    Ping,
    PlayerId,
    RunSilent,
    ShipState,
    resolve,
)

P1 = PlayerId.P1
P2 = PlayerId.P2


def make_state(
    p1: Coord,
    p2: Coord,
    *,
    round: int = 1,
    hull: int = 1,
    config: GameConfig = DEFAULT,
) -> GameState:
    return GameState(
        ships={
            P1: ShipState(position=p1, hull=hull),
            P2: ShipState(position=p2, hull=hull),
        },
        round=round,
        rng_seed=0,
        config=config,
    )


def rng() -> random.Random:
    return random.Random(0)


def test_a_full_round_resolves_correctly() -> None:
    state = make_state((10, 10), (16, 13))

    new_state, events = resolve(state, Move("E"), Fire((10, 10)), rng())

    assert new_state.ships[P1].position == (12, 10)
    assert new_state.ships[P2].position == (16, 13)

    assert {(e.source, e.kind, e.position) for e in events.emissions} == {
        (P1, "HEAT", (12, 10)),
        (P2, "LAUNCH", (16, 13)),
    }

    assert len(events.detonations) == 1
    assert events.detonations[0].target == (10, 10)
    assert events.detonations[0].caught == ()

    assert new_state.ships[P1].hull == 1
    assert new_state.ships[P1].alive
    assert new_state.outcome is Outcome.ONGOING
    assert new_state.round == 2
    assert events.round == 1
    assert events.results[P1].you_were_hit is False
    assert events.results[P2].you_hit_enemy is False


@pytest.mark.parametrize(
    ("start", "direction", "expected"),
    [
        ((10, 10), "N", (10, 12)),
        ((10, 10), "NE", (12, 12)),
        ((10, 10), "E", (12, 10)),
        ((10, 10), "SE", (12, 8)),
        ((10, 10), "S", (10, 8)),
        ((10, 10), "SW", (8, 8)),
        ((10, 10), "W", (8, 10)),
        ((10, 10), "NW", (8, 12)),
    ],
)
def test_each_direction_moves_the_full_distance(
    start: Coord, direction: str, expected: Coord
) -> None:
    state = make_state(start, (0, 0))

    new_state, _ = resolve(state, Move(direction), RunSilent(), rng())

    assert new_state.ships[P1].position == expected


@pytest.mark.parametrize(
    ("start", "direction", "expected"),
    [
        ((0, 0), "W", (0, 0)),
        ((0, 0), "SW", (0, 0)),
        ((1, 1), "SW", (0, 0)),
        ((24, 24), "NE", (24, 24)),
        ((23, 23), "NE", (24, 24)),
        ((0, 12), "NW", (0, 14)),
        ((24, 12), "SE", (24, 10)),
    ],
)
def test_a_move_into_a_wall_clamps_rather_than_failing(
    start: Coord, direction: str, expected: Coord
) -> None:
    state = make_state(start, (12, 0))

    new_state, _ = resolve(state, Move(direction), RunSilent(), rng())

    assert new_state.ships[P1].position == expected


def test_two_ships_may_end_a_round_on_the_same_cell() -> None:
    state = make_state((10, 10), (14, 10))

    new_state, _ = resolve(state, Move("E"), Move("W"), rng())

    assert new_state.ships[P1].position == new_state.ships[P2].position == (12, 10)
    assert new_state.ships[P1].alive and new_state.ships[P2].alive
    assert new_state.outcome is Outcome.ONGOING


@pytest.mark.parametrize(
    "enemy_cell",
    [
        (10, 10),
        (9, 9),
        (9, 10),
        (9, 11),
        (10, 9),
        (10, 11),
        (11, 9),
        (11, 10),
        (11, 11),
    ],
)
def test_anything_inside_the_3x3_is_hit(enemy_cell: Coord) -> None:
    state = make_state((20, 20), enemy_cell)

    new_state, events = resolve(state, Fire((10, 10)), RunSilent(), rng())

    assert new_state.ships[P2].hull == 0
    assert not new_state.ships[P2].alive
    assert events.detonations[0].caught == (P2,)
    assert events.results[P1].you_hit_enemy is True
    assert events.results[P2].you_were_hit is True


@pytest.mark.parametrize(
    "enemy_cell",
    [(8, 10), (12, 10), (10, 8), (10, 12), (8, 8), (12, 12), (9, 12), (12, 11)],
)
def test_anything_just_outside_the_3x3_is_missed(enemy_cell: Coord) -> None:
    state = make_state((20, 20), enemy_cell)

    new_state, events = resolve(state, Fire((10, 10)), RunSilent(), rng())

    assert new_state.ships[P2].hull == 1
    assert new_state.ships[P2].alive
    assert events.detonations[0].caught == ()
    assert events.results[P1].you_hit_enemy is False


def test_moving_out_of_a_targeted_cell_dodges_the_torpedo() -> None:
    state = make_state((0, 0), (10, 10))

    new_state, events = resolve(state, Fire((10, 10)), Move("E"), rng())

    assert new_state.ships[P2].position == (12, 10)
    assert new_state.ships[P2].alive
    assert events.detonations[0].caught == ()


def test_moving_only_to_the_blast_edge_does_not_dodge() -> None:
    state = make_state((0, 0), (10, 12))

    new_state, _ = resolve(state, Fire((10, 10)), Move("S"), rng())

    assert new_state.ships[P2].position == (10, 10)
    assert not new_state.ships[P2].alive


def test_a_ship_is_not_caught_in_its_own_blast() -> None:
    state = make_state((10, 10), (20, 20))

    new_state, events = resolve(state, Fire((10, 10)), RunSilent(), rng())

    assert new_state.ships[P1].alive
    assert events.detonations[0].caught == ()


def test_a_hit_decrements_the_hull_without_killing_a_tougher_ship() -> None:
    state = make_state((0, 0), (10, 10), hull=2)

    new_state, events = resolve(state, Fire((10, 10)), RunSilent(), rng())

    assert new_state.ships[P2].hull == 1
    assert new_state.ships[P2].alive
    assert new_state.outcome is Outcome.ONGOING
    assert events.results[P2].you_were_hit is True


def test_successive_hits_eventually_kill() -> None:
    state = make_state((0, 0), (10, 10), hull=2)

    state, _ = resolve(state, Fire((10, 10)), RunSilent(), rng())
    state, _ = resolve(state, Fire((10, 10)), RunSilent(), rng())

    assert state.ships[P2].hull == 0
    assert not state.ships[P2].alive
    assert state.outcome is Outcome.P1_WINS


def test_killing_the_enemy_wins_the_match() -> None:
    state = make_state((0, 0), (10, 10))

    new_state, _ = resolve(state, Fire((10, 10)), RunSilent(), rng())

    assert new_state.outcome is Outcome.P1_WINS


def test_p2_can_win_too() -> None:
    state = make_state((10, 10), (0, 0))

    new_state, _ = resolve(state, RunSilent(), Fire((10, 10)), rng())

    assert new_state.outcome is Outcome.P2_WINS


def test_simultaneous_double_kill_is_a_draw() -> None:
    state = make_state((5, 5), (15, 15))

    new_state, events = resolve(state, Fire((15, 15)), Fire((5, 5)), rng())

    assert not new_state.ships[P1].alive
    assert not new_state.ships[P2].alive
    assert new_state.outcome is Outcome.DRAW
    assert events.results[P1].you_hit_enemy is True
    assert events.results[P1].you_were_hit is True
    assert events.results[P2].you_hit_enemy is True
    assert events.results[P2].you_were_hit is True


def test_reaching_the_round_cap_with_both_alive_is_a_draw() -> None:
    state = make_state((0, 0), (24, 24), round=DEFAULT.round_cap)

    new_state, _ = resolve(state, RunSilent(), RunSilent(), rng())

    assert new_state.round == DEFAULT.round_cap + 1
    assert new_state.outcome is Outcome.DRAW


def test_the_round_before_the_cap_is_still_ongoing() -> None:
    state = make_state((0, 0), (24, 24), round=DEFAULT.round_cap - 1)

    new_state, _ = resolve(state, RunSilent(), RunSilent(), rng())

    assert new_state.outcome is Outcome.ONGOING


def test_a_kill_on_the_final_round_is_a_win_not_a_draw() -> None:
    state = make_state((0, 0), (10, 10), round=DEFAULT.round_cap)

    new_state, _ = resolve(state, Fire((10, 10)), RunSilent(), rng())

    assert new_state.outcome is Outcome.P1_WINS


def test_a_finished_match_cannot_be_resolved_again() -> None:
    state = make_state((0, 0), (10, 10))
    finished, _ = resolve(state, Fire((10, 10)), RunSilent(), rng())

    with pytest.raises(ValueError, match="has ended"):
        resolve(finished, RunSilent(), RunSilent(), rng())


def test_running_silent_emits_nothing() -> None:
    state = make_state((10, 10), (16, 13))

    _, events = resolve(state, RunSilent(), RunSilent(), rng())

    assert events.emissions == ()


@pytest.mark.parametrize(
    ("action", "kind"),
    [(Move("E"), "HEAT"), (Fire((0, 0)), "LAUNCH"), (Ping(), "PING")],
)
def test_every_other_action_emits(action: object, kind: str) -> None:
    state = make_state((10, 10), (16, 13))

    _, events = resolve(state, action, RunSilent(), rng())

    assert [(e.source, e.kind) for e in events.emissions] == [(P1, kind)]


def test_an_emission_is_recorded_at_the_post_move_cell() -> None:
    state = make_state((10, 10), (16, 13))

    _, events = resolve(state, Move("N"), RunSilent(), rng())

    assert events.emissions[0].position == (10, 12)


def test_the_round_events_ride_on_the_new_state() -> None:
    state = make_state((10, 10), (16, 13))

    new_state, events = resolve(state, Move("E"), Ping(), rng())

    assert new_state.last_events is events


def test_a_fresh_match_has_no_prior_events() -> None:
    from engine import new_match

    assert new_match(seed=1).last_events is None


def test_the_engine_grants_no_fix_for_a_ping() -> None:
    state = make_state((10, 10), (11, 11))

    _, events = resolve(state, Ping(), RunSilent(), rng())

    assert events.emissions[0].kind == "PING"
    assert events.detonations == ()


def test_resolve_is_deterministic() -> None:
    state = make_state((10, 10), (16, 13))

    first = resolve(state, Move("NE"), Fire((12, 12)), random.Random(99))
    second = resolve(state, Move("NE"), Fire((12, 12)), random.Random(99))

    assert first == second


def test_resolve_does_not_mutate_the_state_it_was_given() -> None:
    state = make_state((10, 10), (10, 11))

    resolve(state, Move("NE"), Fire((10, 11)), rng())

    assert state.ships[P1].position == (10, 10)
    assert state.ships[P2].position == (10, 11)
    assert state.ships[P2].hull == 1
    assert state.ships[P2].alive
    assert state.round == 1
    assert state.outcome is Outcome.ONGOING


def test_resolve_honours_a_non_default_config() -> None:
    brisk = replace(DEFAULT, move_distance=5, blast_radius=2)
    state = make_state((10, 10), (12, 12), config=brisk)

    new_state, events = resolve(state, Move("E"), RunSilent(), rng())

    assert new_state.ships[P1].position == (15, 10)

    state = make_state((0, 0), (12, 12), config=brisk)
    _, events = resolve(state, Fire((10, 10)), RunSilent(), rng())
    assert events.detonations[0].caught == (P2,)


def test_an_invalid_action_is_refused_before_anything_moves() -> None:
    from engine import InvalidAction

    state = make_state((10, 10), (16, 13))

    with pytest.raises(InvalidAction):
        resolve(state, Move("UP"), RunSilent(), rng())
    with pytest.raises(InvalidAction):
        resolve(state, RunSilent(), Fire((99, 99)), rng())

    assert state.ships[P1].position == (10, 10)
