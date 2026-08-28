from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from config import DEFAULT
from engine import Outcome, PlayerId, RunSilent
from server.app import app, store

TIMEOUT = DEFAULT.turn_timeout_s
GRACE = DEFAULT.grace_window_s
ABANDON = DEFAULT.abandon_after_s


class FakeClock:
    """Time we can push forward, so a 90 second rule takes no seconds to test."""

    def __init__(self, start: float = 10_000.0) -> None:
        self.time = start

    def __call__(self) -> float:
        return self.time

    def advance(self, seconds: float) -> None:
        self.time += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(clock: FakeClock) -> Iterator[TestClient]:
    store.clear()
    original = store.clock
    store.clock = clock
    with TestClient(app) as test_client:
        yield test_client
    store.clock = original
    store.clear()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def start_match(client: TestClient) -> tuple[str, str, str]:
    created = client.post("/matches").json()
    joined = client.post(f"/matches/{created['match_id']}/join").json()
    return created["match_id"], created["token"], joined["token"]


def view_of(client: TestClient, match_id: str, token: str) -> dict:
    return client.get(f"/matches/{match_id}/view", headers=auth(token)).json()


def act(client: TestClient, match_id: str, token: str, **body: object):
    return client.post(f"/matches/{match_id}/action", json=body, headers=auth(token))


# --- Liveness ---------------------------------------------------------------


def test_polling_is_the_heartbeat(client: TestClient, clock: FakeClock) -> None:
    match_id, token_p1, _ = start_match(client)
    clock.advance(30)

    view_of(client, match_id, token_p1)

    assert store.get(match_id).last_seen[PlayerId.P1] == clock.time


def test_submitting_an_action_also_counts_as_being_present(
    client: TestClient, clock: FakeClock
) -> None:
    match_id, token_p1, _ = start_match(client)
    clock.advance(30)

    act(client, match_id, token_p1, type="RUN_SILENT")

    assert store.get(match_id).last_seen[PlayerId.P1] == clock.time


# --- Turn timeout -----------------------------------------------------------


def test_a_missed_turn_becomes_run_silent_and_the_round_moves_on(
    client: TestClient, clock: FakeClock
) -> None:
    """The no-leak default: a player who says nothing gives nothing away."""
    match_id, token_p1, token_p2 = start_match(client)
    act(client, match_id, token_p2, type="MOVE", direction="N")

    clock.advance(TIMEOUT + 1)
    view = view_of(client, match_id, token_p1)

    assert view["round"] == 2
    record = store.get(match_id)
    assert isinstance(record.history[0].actions[PlayerId.P1], RunSilent)
    assert record.timeouts[PlayerId.P1] == 1
    assert record.timeouts[PlayerId.P2] == 0


def test_a_round_is_not_forced_early(client: TestClient, clock: FakeClock) -> None:
    match_id, token_p1, token_p2 = start_match(client)
    act(client, match_id, token_p2, type="PING")

    clock.advance(TIMEOUT - 1)

    assert view_of(client, match_id, token_p1)["round"] == 1


def test_three_missed_turns_in_a_row_forfeit_the_match(
    client: TestClient, clock: FakeClock
) -> None:
    """The player is present the whole time - they poll, they just never act."""
    match_id, token_p1, token_p2 = start_match(client)

    for _ in range(DEFAULT.max_consecutive_timeouts):
        act(client, match_id, token_p2, type="RUN_SILENT")
        clock.advance(TIMEOUT + 1)
        view_of(client, match_id, token_p1)

    assert store.get(match_id).state.outcome is Outcome.P2_WINS
    assert view_of(client, match_id, token_p1)["outcome"] == "LOSS"
    assert view_of(client, match_id, token_p2)["outcome"] == "WIN"


def test_acting_clears_the_strike_count(client: TestClient, clock: FakeClock) -> None:
    match_id, token_p1, token_p2 = start_match(client)

    for _ in range(4):
        act(client, match_id, token_p2, type="RUN_SILENT")
        clock.advance(TIMEOUT + 1)
        view_of(client, match_id, token_p1)
        act(client, match_id, token_p1, type="RUN_SILENT")
        act(client, match_id, token_p2, type="RUN_SILENT")

    assert store.get(match_id).state.outcome is Outcome.ONGOING


def test_both_players_going_quiet_at_once_is_a_draw(
    client: TestClient, clock: FakeClock
) -> None:
    match_id, token_p1, _ = start_match(client)

    for _ in range(DEFAULT.max_consecutive_timeouts):
        clock.advance(TIMEOUT + 1)
        store.get(match_id).last_seen[PlayerId.P2] = clock.time
        view_of(client, match_id, token_p1)

    assert store.get(match_id).state.outcome is Outcome.DRAW


# --- Grace and abandonment --------------------------------------------------


def test_a_quiet_opponent_is_reported_as_in_grace(
    client: TestClient, clock: FakeClock
) -> None:
    match_id, token_p1, token_p2 = start_match(client)

    clock.advance(GRACE + 1)
    act(client, match_id, token_p2, type="RUN_SILENT")

    assert view_of(client, match_id, token_p2)["opponent_status"] == (
        "DISCONNECTED_GRACE"
    )


def test_a_present_opponent_is_reported_as_connected(
    client: TestClient, clock: FakeClock
) -> None:
    match_id, token_p1, token_p2 = start_match(client)

    clock.advance(GRACE - 1)
    view_of(client, match_id, token_p1)

    assert view_of(client, match_id, token_p2)["opponent_status"] == "CONNECTED"


def test_abandoning_the_match_hands_it_to_the_opponent(
    client: TestClient, clock: FakeClock
) -> None:
    """P2 keeps polling throughout; P1 says nothing at all."""
    match_id, _, token_p2 = start_match(client)
    opened = clock.time

    for elapsed in (45, 100, 150, ABANDON + 1):
        clock.time = opened + elapsed
        view_of(client, match_id, token_p2)

    assert store.get(match_id).state.outcome is Outcome.P2_WINS
    assert view_of(client, match_id, token_p2)["outcome"] == "WIN"


def test_both_abandoning_voids_the_match(client: TestClient, clock: FakeClock) -> None:
    match_id, token_p1, _ = start_match(client)

    clock.advance(ABANDON + 1)
    view = view_of(client, match_id, token_p1)

    assert store.get(match_id).state.outcome is Outcome.DRAW
    assert view["outcome"] == "DRAW"


def test_returning_after_the_abandon_threshold_is_too_late(
    client: TestClient, clock: FakeClock
) -> None:
    """The match ended at the threshold; nobody had asked yet, that is all."""
    match_id, token_p1, token_p2 = start_match(client)

    clock.advance(ABANDON + 1)
    store.get(match_id).last_seen[PlayerId.P2] = clock.time
    view = view_of(client, match_id, token_p1)

    assert view["outcome"] == "LOSS"


# --- Reconnection -----------------------------------------------------------


def test_a_player_who_goes_quiet_and_comes_back_simply_resumes(
    client: TestClient, clock: FakeClock
) -> None:
    """Nothing to re-establish: the token is the whole session."""
    match_id, token_p1, token_p2 = start_match(client)
    act(client, match_id, token_p1, type="MOVE", direction="N")
    act(client, match_id, token_p2, type="MOVE", direction="S")

    clock.advance(GRACE + 5)
    act(client, match_id, token_p2, type="RUN_SILENT")
    assert view_of(client, match_id, token_p2)["opponent_status"] == (
        "DISCONNECTED_GRACE"
    )

    resumed = view_of(client, match_id, token_p1)

    assert resumed["outcome"] == "ONGOING"
    assert resumed["round"] == 2
    assert view_of(client, match_id, token_p2)["opponent_status"] == "CONNECTED"
    assert act(client, match_id, token_p1, type="PING").status_code == 200


def test_the_match_survives_a_reconnect_and_plays_on(
    client: TestClient, clock: FakeClock
) -> None:
    match_id, token_p1, token_p2 = start_match(client)

    clock.advance(GRACE + 5)
    view_of(client, match_id, token_p1)

    for _ in range(3):
        act(client, match_id, token_p1, type="RUN_SILENT")
        act(client, match_id, token_p2, type="RUN_SILENT")

    assert store.get(match_id).state.outcome is Outcome.ONGOING
    assert store.get(match_id).state.round == 4


# --- Seats that cannot go quiet --------------------------------------------


def test_a_bot_is_never_reported_as_absent(
    client: TestClient, clock: FakeClock
) -> None:
    created = client.post("/matches", json={"opponent": "ai", "level": 1}).json()
    match_id, token = created["match_id"], created["token"]

    clock.advance(ABANDON * 3)

    assert view_of(client, match_id, token)["opponent_status"] == "CONNECTED"


def test_a_human_can_still_forfeit_against_a_bot(
    client: TestClient, clock: FakeClock
) -> None:
    created = client.post("/matches", json={"opponent": "ai", "level": 1}).json()
    match_id, token = created["match_id"], created["token"]

    for _ in range(DEFAULT.max_consecutive_timeouts):
        clock.advance(TIMEOUT + 1)
        store.get(match_id).last_seen[PlayerId.P1] = clock.time
        view_of(client, match_id, token)

    assert store.get(match_id).state.outcome is Outcome.P2_WINS


def test_the_clock_does_not_run_before_an_opponent_arrives(
    client: TestClient, clock: FakeClock
) -> None:
    """Nobody is late for a match that has not started."""
    created = client.post("/matches").json()
    match_id, token = created["match_id"], created["token"]

    clock.advance(ABANDON * 2)
    view = view_of(client, match_id, token)

    assert view["outcome"] == "ONGOING"
    assert store.get(match_id).state.round == 1
