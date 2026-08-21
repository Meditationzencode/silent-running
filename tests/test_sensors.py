"""The sensor model, unit by unit, against the numbers in the spec.

Design §7 item 4: noise stays within its sigma bounds, buckets map correctly at
their boundaries (6/7, 12/13, 18/19), out-of-range emissions yield no contact,
and an out-of-range ping yields no fix.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import replace

import pytest

from config import DEFAULT
from engine import (
    Fire,
    GameState,
    Move,
    Ping,
    PlayerId,
    RunSilent,
    ShipState,
    resolve,
)
from perception import (
    active_fix,
    bearing_sigma_deg,
    noised_bearing_deg,
    passive_contact,
    ping_detected,
    range_bucket,
    true_bearing_deg,
    view_for,
)

P1, P2 = PlayerId.P1, PlayerId.P2


def two_ships(p1, p2, config=DEFAULT) -> GameState:
    return GameState(
        ships={P1: ShipState(p1, 1), P2: ShipState(p2, 1)},
        round=1,
        rng_seed=0,
        config=config,
    )


def contacts_for(state, action_p1, action_p2, player=P1, seed=0):
    """Resolve one round and return what ``player`` perceived."""
    resolved, _ = resolve(state, action_p1, action_p2, random.Random(seed))
    return view_for(resolved, player, random.Random(seed)).contacts


# --- Bearings ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ((11, 10), 0.0),  # due east
        ((10, 11), 90.0),  # due north
        ((9, 10), 180.0),  # due west
        ((10, 9), 270.0),  # due south
        ((11, 11), 45.0),  # north-east
        ((9, 9), 225.0),
    ],
)
def test_true_bearing_uses_the_prd_convention(target, expected: float) -> None:
    """0 deg = east, 90 deg = north, counter-clockwise (PRD §4)."""
    assert true_bearing_deg((10, 10), target) == pytest.approx(expected)


def test_true_bearing_matches_the_prd_worked_example() -> None:
    """(10,10) -> (14,13) is atan2(3, 4) ~= 36.9 deg."""
    assert true_bearing_deg((10, 10), (14, 13)) == pytest.approx(36.87, abs=0.01)


@pytest.mark.parametrize(
    ("distance", "expected"),
    [(0.0, 4.0), (5.0, 7.0), (15.0, 13.0), (6.708, 8.0248)],
)
def test_sigma_grows_with_range(distance: float, expected: float) -> None:
    """sigma = 4 + 0.6*d. The 5-cell and 15-cell values are quoted in PRD §4."""
    assert bearing_sigma_deg(distance) == pytest.approx(expected, abs=1e-3)


def test_noise_matches_its_stated_distribution() -> None:
    """Over many seeded samples the error really is N(0, sigma).

    Checks both moments. A wrong mean would mean a biased sensor (every contact
    reading a few degrees clockwise); a wrong spread would mean the fog is
    thicker or thinner than the design says, which is a balance change smuggled
    in as a bug.
    """
    origin, target = (10, 10), (15, 15)  # 7.07 cells apart, true bearing 45 deg
    sigma = bearing_sigma_deg(7.0710678)
    rng = random.Random(20260821)

    samples = [noised_bearing_deg(origin, target, rng) for _ in range(20000)]

    assert statistics.fmean(samples) == pytest.approx(45.0, abs=0.4)
    assert statistics.stdev(samples) == pytest.approx(sigma, rel=0.03)


def test_a_reported_bearing_is_not_the_true_one() -> None:
    """The point of the whole layer: you get a direction, not the direction."""
    rng = random.Random(7)
    samples = [noised_bearing_deg((10, 10), (14, 13), rng) for _ in range(200)]

    assert len(set(samples)) > 100, "the bearing barely varies"
    assert sum(s == pytest.approx(36.87, abs=0.05) for s in samples) < 10


def test_bearings_wrap_instead_of_going_negative() -> None:
    """Due east plus a negative draw must come back as ~359, never as -1."""
    rng = random.Random(3)
    samples = [noised_bearing_deg((10, 10), (20, 10), rng) for _ in range(2000)]

    assert all(0.0 <= s < 360.0 for s in samples)
    assert any(s > 300.0 for s in samples), "nothing ever wrapped below zero"


# --- Range buckets ----------------------------------------------------------


@pytest.mark.parametrize(
    ("distance", "expected"),
    [
        (0.0, "CLOSE"),
        (5.9, "CLOSE"),
        (6.0, "CLOSE"),  # boundary: <= 6 is CLOSE
        (6.1, "MEDIUM"),
        (7.0, "MEDIUM"),
        (12.0, "MEDIUM"),  # boundary: <= 12 is MEDIUM
        (12.1, "FAR"),
        (13.0, "FAR"),
        (18.0, "FAR"),  # boundary: <= 18 is FAR
        (18.1, None),  # past passive range: unheard entirely
        (19.0, None),
        (100.0, None),
    ],
)
def test_bucket_boundaries(distance: float, expected: str | None) -> None:
    """The 6/7, 12/13, 18/19 boundaries design §7 asks for, read continuously."""
    assert range_bucket(distance) == expected


def test_buckets_follow_the_config_not_hardcoded_numbers() -> None:
    tight = replace(DEFAULT, bucket_close_max=2.0, bucket_medium_max=4.0, passive_range=6.0)

    assert range_bucket(2.0, tight) == "CLOSE"
    assert range_bucket(3.0, tight) == "MEDIUM"
    assert range_bucket(5.0, tight) == "FAR"
    assert range_bucket(7.0, tight) is None


# --- Passive and launch contacts -------------------------------------------


def test_a_passive_contact_never_carries_a_position() -> None:
    contact = passive_contact((10, 10), (14, 13), "HEAT", random.Random(0))

    assert contact is not None
    assert contact.kind == "PASSIVE_BEARING"
    assert contact.exact_position is None
    assert contact.range_bucket == "CLOSE"


def test_a_launch_is_detected_exactly_like_a_move() -> None:
    """Same noise, same bucket, different label — PRD §4."""
    heat = passive_contact((10, 10), (16, 13), "HEAT", random.Random(11))
    launch = passive_contact((10, 10), (16, 13), "LAUNCH", random.Random(11))

    assert heat is not None and launch is not None
    assert heat.kind == "PASSIVE_BEARING"
    assert launch.kind == "LAUNCH_DETECTED"
    assert launch.bearing_deg == heat.bearing_deg
    assert launch.range_bucket == heat.range_bucket == "MEDIUM"
    assert launch.exact_position is None


def test_an_emission_beyond_passive_range_is_unheard() -> None:
    assert passive_contact((0, 0), (19, 0), "HEAT", random.Random(0)) is None


def test_an_emission_at_exactly_passive_range_is_heard() -> None:
    contact = passive_contact((0, 0), (18, 0), "HEAT", random.Random(0))

    assert contact is not None
    assert contact.range_bucket == "FAR"


# --- Ping -------------------------------------------------------------------


def test_a_ping_always_reveals_the_pinger() -> None:
    """No range gate at all: loud is loud."""
    assert ping_detected((3, 4)).exact_position == (3, 4)
    assert ping_detected((3, 4)).kind == "PING_DETECTED"


@pytest.mark.parametrize("enemy", [(10, 10), (22, 10), (10, 22)])
def test_an_active_fix_is_exact_when_the_enemy_is_in_range(enemy) -> None:
    fix = active_fix((10, 10), enemy)

    assert fix is not None
    assert fix.kind == "ACTIVE_FIX"
    assert fix.exact_position == enemy
    assert fix.bearing_deg is None
    assert fix.range_bucket is None


def test_no_active_fix_beyond_ping_range() -> None:
    """13 cells: nothing comes back, and you emitted anyway."""
    assert active_fix((10, 10), (23, 10)) is None


def test_active_fix_at_exactly_ping_range_still_works() -> None:
    assert active_fix((10, 10), (22, 10)) is not None


# --- End to end through view_for -------------------------------------------


def test_the_prd_passive_worked_example() -> None:
    """Enemy at (16,13) moves to (14,13); you at (10,10) hear it CLOSE."""
    contacts = contacts_for(two_ships((10, 10), (16, 13)), RunSilent(), Move("W"))

    assert len(contacts) == 1
    assert contacts[0].kind == "PASSIVE_BEARING"
    assert contacts[0].range_bucket == "CLOSE"
    assert contacts[0].exact_position is None
    assert contacts[0].bearing_deg != pytest.approx(36.87, abs=0.01)


def test_the_prd_ping_worked_example() -> None:
    """You ping at 6.7 cells: you get a fix, and they get yours."""
    state = two_ships((10, 10), (16, 13))
    resolved, _ = resolve(state, Ping(), RunSilent(), random.Random(0))

    yours = view_for(resolved, P1, random.Random(0)).contacts
    theirs = view_for(resolved, P2, random.Random(0)).contacts

    assert [c.kind for c in yours] == ["ACTIVE_FIX"]
    assert yours[0].exact_position == (16, 13)
    assert [c.kind for c in theirs] == ["PING_DETECTED"]
    assert theirs[0].exact_position == (10, 10)


def test_a_wasted_ping_reveals_you_and_returns_nothing() -> None:
    """13 cells apart: their contacts list is full, yours is empty."""
    state = two_ships((10, 10), (23, 10))
    resolved, _ = resolve(state, Ping(), RunSilent(), random.Random(0))

    assert view_for(resolved, P1, random.Random(0)).contacts == ()
    assert view_for(resolved, P2, random.Random(0)).contacts[0].exact_position == (10, 10)


def test_mutual_silence_yields_nothing_to_either_player() -> None:
    state = two_ships((10, 10), (11, 11))
    resolved, _ = resolve(state, RunSilent(), RunSilent(), random.Random(0))

    assert view_for(resolved, P1, random.Random(0)).contacts == ()
    assert view_for(resolved, P2, random.Random(0)).contacts == ()


def test_a_mutual_ping_gives_both_players_two_contacts() -> None:
    """Ping into a ping: you each pay, and you each learn."""
    state = two_ships((10, 10), (14, 14))
    resolved, _ = resolve(state, Ping(), Ping(), random.Random(0))

    for player, enemy_cell, own_cell in ((P1, (14, 14), (10, 10)), (P2, (10, 10), (14, 14))):
        contacts = view_for(resolved, player, random.Random(0)).contacts
        kinds = {c.kind for c in contacts}
        assert kinds == {"PING_DETECTED", "ACTIVE_FIX"}
        assert {c.exact_position for c in contacts} == {enemy_cell}
        assert own_cell not in {c.exact_position for c in contacts}


def test_an_out_of_range_move_produces_no_contact_end_to_end() -> None:
    """Enemy burns from (21,0) to (19,0): 19 cells away, unheard."""
    contacts = contacts_for(two_ships((0, 0), (21, 0)), RunSilent(), Move("W"))

    assert contacts == ()


def test_a_dead_enemys_emission_is_still_reported() -> None:
    """Emissions are recorded before detonation, so a last gasp still carries."""
    state = two_ships((10, 10), (14, 10))
    # P2 burns north into (14,12) and P1 has guessed that cell, so P2 emits and
    # then dies in the same round.
    resolved, _ = resolve(state, Fire((14, 12)), Move("N"), random.Random(0))

    assert not resolved.ships[P2].alive
    assert [c.kind for c in view_for(resolved, P1, random.Random(0)).contacts] == [
        "PASSIVE_BEARING"
    ]


def test_a_fresh_match_shows_no_contacts_and_no_result() -> None:
    """Before round one there is nothing to have perceived."""
    view = view_for(two_ships((0, 0), (5, 5)), P1, random.Random(0))

    assert view.contacts == ()
    assert view.last_result is None
    assert view.outcome == "ONGOING"


@pytest.mark.parametrize(
    ("winner_action", "p1_outcome", "p2_outcome"),
    [(Fire((14, 10)), "WIN", "LOSS")],
)
def test_outcome_is_reported_from_each_players_seat(
    winner_action, p1_outcome: str, p2_outcome: str
) -> None:
    state = two_ships((10, 10), (14, 10))
    resolved, _ = resolve(state, winner_action, RunSilent(), random.Random(0))

    assert view_for(resolved, P1, random.Random(0)).outcome == p1_outcome
    assert view_for(resolved, P2, random.Random(0)).outcome == p2_outcome


def test_a_draw_reads_as_a_draw_to_both_players() -> None:
    state = two_ships((5, 5), (15, 15))
    resolved, _ = resolve(state, Fire((15, 15)), Fire((5, 5)), random.Random(0))

    assert view_for(resolved, P1, random.Random(0)).outcome == "DRAW"
    assert view_for(resolved, P2, random.Random(0)).outcome == "DRAW"


def test_each_player_sees_only_their_own_ship() -> None:
    state = two_ships((3, 4), (20, 21))
    resolved, _ = resolve(state, RunSilent(), RunSilent(), random.Random(0))

    assert view_for(resolved, P1, random.Random(0)).your_ship.position == (3, 4)
    assert view_for(resolved, P2, random.Random(0)).your_ship.position == (20, 21)
