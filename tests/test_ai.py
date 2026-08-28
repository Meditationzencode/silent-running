from __future__ import annotations

import ast
import random
from pathlib import Path

import pytest

from ai import LEVELS, Belief, make_bot
from engine import Contact, Outcome, ShipState, validate_action
from perception import PlayerView
from tests.arena import play_match

LADDER_SEEDS = 30
PAIRINGS = [(high, low) for high in sorted(LEVELS) for low in range(1, high)]


def view(
    position: tuple[int, int], contacts: tuple[Contact, ...] = (), round: int = 2
) -> PlayerView:
    return PlayerView(
        round=round,
        phase="RESOLVED",
        your_ship=ShipState(position=position, hull=1),
        contacts=contacts,
        last_result=None,
        opponent_status="CONNECTED",
        outcome="ONGOING",
    )


def duel(high: int, low: int, seeds: int = LADDER_SEEDS) -> tuple[int, int, int]:
    """Play both seatings of every seed, so a seat edge cannot look like skill."""
    wins_high = wins_low = draws = 0
    for seed in range(seeds):
        for swapped in (False, True):
            first, second = (low, high) if swapped else (high, low)
            result = play_match(
                make_bot(first, random.Random(seed * 7 + 1)),
                make_bot(second, random.Random(seed * 7 + 2)),
                seed=seed,
            )
            if result.outcome is Outcome.DRAW:
                draws += 1
            elif (result.outcome is Outcome.P1_WINS) != swapped:
                wins_high += 1
            else:
                wins_low += 1
    return wins_high, wins_low, draws


# --- The rule the whole module exists under --------------------------------


def test_no_bot_module_imports_the_truth() -> None:
    """Difficulty is inference quality, never information. Enforced, not trusted.

    Checks imports rather than the text of the file, so a docstring may say the
    word GameState while the module remains structurally unable to hold one.
    """
    forbidden = {"GameState", "view_for", "RoundEvents", "resolve"}

    for module in sorted(Path("ai").glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        leaked = imported & forbidden
        assert not leaked, f"{module} imports {sorted(leaked)}"


@pytest.mark.parametrize("level", sorted(LEVELS))
def test_a_bot_decides_from_a_player_view_alone(level: int) -> None:
    bot = make_bot(level, random.Random(1))

    action = bot.choose_action(view((10, 10)))

    validate_action(action)


# --- Legality ---------------------------------------------------------------


@pytest.mark.parametrize("level", sorted(LEVELS))
def test_every_action_a_level_submits_is_legal(level: int) -> None:
    for seed in range(6):
        result = play_match(
            make_bot(level, random.Random(seed)),
            make_bot(1, random.Random(seed + 100)),
            seed=seed,
        )
        for _, action in result.actions:
            validate_action(action)


@pytest.mark.parametrize("level", sorted(LEVELS))
def test_every_level_plays_a_match_to_a_conclusion(level: int) -> None:
    result = play_match(
        make_bot(level, random.Random(3)), make_bot(1, random.Random(4)), seed=3
    )

    assert result.outcome is not Outcome.ONGOING
    assert 0 < result.rounds <= 50


def test_an_unknown_level_is_refused() -> None:
    with pytest.raises(ValueError, match="no such level"):
        make_bot(9)


def test_the_same_seed_gives_the_same_match() -> None:
    def run() -> Outcome:
        return play_match(
            make_bot(4, random.Random(11)), make_bot(3, random.Random(12)), seed=5
        ).outcome

    assert run() is run()


# --- The ladder -------------------------------------------------------------


@pytest.mark.parametrize(("high", "low"), PAIRINGS)
def test_a_higher_level_beats_a_lower_one(high: int, low: int) -> None:
    """Over seeded head-to-head matches, the ladder holds in every pairing.

    Deterministic rather than statistical: every match is seeded, so this is a
    fixed result, not a sample that might come out differently on a rerun.
    """
    wins_high, wins_low, _ = duel(high, low)
    decisive = wins_high + wins_low

    assert decisive > 0, "every match was drawn; nothing was measured"
    assert wins_high / decisive > 0.5, (
        f"level {high} ({LEVELS[high].name}) beat level {low} ({LEVELS[low].name}) "
        f"in only {wins_high}/{decisive} decisive matches"
    )


def test_the_top_level_beats_the_bottom_one_decisively() -> None:
    wins_high, wins_low, _ = duel(5, 1)

    assert wins_high / (wins_high + wins_low) > 0.85


# --- The belief, which levels 3 to 5 are built on --------------------------


def test_a_fresh_belief_spans_the_whole_board() -> None:
    assert Belief().size == 25 * 25


def test_an_exact_fix_collapses_the_belief_to_one_cell() -> None:
    belief = Belief()

    belief.advance(
        view((10, 10), (Contact(kind="ACTIVE_FIX", exact_position=(16, 13)),))
    )

    assert belief.cells == {(16, 13)}
    assert belief.is_pinned


def test_a_bearing_narrows_the_belief_without_pinning_it() -> None:
    belief = Belief()

    belief.advance(
        view(
            (10, 10),
            (
                Contact(
                    kind="PASSIVE_BEARING", bearing_deg=45.0, range_bucket="CLOSE"
                ),
            ),
        )
    )

    assert 1 < belief.size < 625
    assert all(cell[0] >= 10 and cell[1] >= 10 for cell in belief.cells)


def test_a_quiet_round_rules_nothing_out() -> None:
    """Run Silent is always available, so silence is not evidence of anything."""
    belief = Belief()
    belief.cells = {(5, 5)}

    belief.advance(view((10, 10)))

    assert belief.size == 9


def test_belief_regrows_between_rounds() -> None:
    belief = Belief()
    belief.advance(
        view((10, 10), (Contact(kind="ACTIVE_FIX", exact_position=(16, 13)),))
    )

    belief.advance(view((10, 10)))

    assert belief.size == 9
    assert (16, 13) in belief.cells


def test_a_confirmed_hit_pins_them_to_the_blast() -> None:
    """Sharper than any bearing: nine cells with no noise on them."""
    belief = Belief()

    belief.confirm_hit((12, 12))

    assert belief.size == 9
    assert (12, 12) in belief.cells
    assert (14, 12) not in belief.cells


def test_a_confirmed_hit_narrows_rather_than_replaces() -> None:
    belief = Belief()
    belief.cells = {(12, 12), (20, 20)}

    belief.confirm_hit((12, 12))

    assert belief.cells == {(12, 12)}


def test_a_hit_at_the_edge_of_the_board_stays_on_the_board() -> None:
    belief = Belief()

    belief.confirm_hit((0, 0))

    assert belief.size == 4
    assert all(0 <= x and 0 <= y for x, y in belief.cells)


@pytest.mark.parametrize("level", [1, 2, 3])
def test_the_lower_levels_learn_nothing_from_a_hit(level: int) -> None:
    """Reading your own hits is a level 4 capability; below that it is wasted."""
    bot = make_bot(level, random.Random(1))

    assert not hasattr(bot, "belief") or bot.belief.size == 625


def test_best_shot_finds_the_cell_covering_most_of_the_belief() -> None:
    belief = Belief()
    belief.cells = {(4, 4), (5, 5), (6, 6), (20, 20)}

    target, quality = belief.best_shot()

    assert target == (5, 5)
    assert quality == pytest.approx(0.75)


def test_a_pinned_belief_is_a_certain_shot_if_they_hold_still() -> None:
    belief = Belief()
    belief.cells = {(12, 12)}

    assert belief.best_shot() == ((12, 12), 1.0)


def test_dodge_weights_leave_most_of_the_weight_where_they_stand() -> None:
    belief = Belief()
    belief.cells = {(12, 12)}

    weights = belief.dodge_weights(0.55)

    assert weights[(12, 12)] == pytest.approx(0.55)
    assert sum(weights.values()) == pytest.approx(1.0)
    assert len(weights) == 9


def test_aiming_at_a_dodge_beats_aiming_at_the_cell_they_left() -> None:
    """The whole of level 4 in one assertion."""
    belief = Belief()
    belief.cells = {(12, 12)}
    weights = belief.dodge_weights(0.55)

    naive_target = belief.best_shot()[0]
    dodge_target, dodge_quality = belief.best_shot(weights)

    naive_quality = sum(
        weight
        for cell, weight in weights.items()
        if max(abs(cell[0] - naive_target[0]), abs(cell[1] - naive_target[1])) <= 1
    )

    assert dodge_quality > naive_quality
