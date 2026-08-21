from __future__ import annotations

from typing import Any

from hypothesis import strategies as st

from config import DEFAULT
from engine import (
    DIRECTION_VECTORS,
    Fire,
    GameState,
    Move,
    Ping,
    PlayerId,
    RunSilent,
    ShipState,
)

MAX_COORD = DEFAULT.grid_size - 1

cells = st.tuples(st.integers(0, MAX_COORD), st.integers(0, MAX_COORD))
seeds = st.integers(min_value=0, max_value=2**32 - 1)
actions = st.one_of(
    st.just(RunSilent()),
    st.just(Ping()),
    st.builds(Move, st.sampled_from(sorted(DIRECTION_VECTORS))),
    st.builds(Fire, cells),
)


@st.composite
def game_states(draw: st.DrawFn) -> GameState:
    hull = draw(st.integers(min_value=1, max_value=3))
    return GameState(
        ships={
            PlayerId.P1: ShipState(position=draw(cells), hull=hull),
            PlayerId.P2: ShipState(position=draw(cells), hull=hull),
        },
        round=draw(st.integers(min_value=1, max_value=DEFAULT.round_cap - 1)),
        rng_seed=draw(seeds),
    )


def coordinates_in(node: Any) -> list[tuple[int, int]]:
    if isinstance(node, dict):
        return [cell for value in node.values() for cell in coordinates_in(value)]
    if isinstance(node, (list, tuple)):
        if len(node) == 2 and all(
            isinstance(v, int) and not isinstance(v, bool) for v in node
        ):
            return [(node[0], node[1])]
        return [cell for value in node for cell in coordinates_in(value)]
    return []
