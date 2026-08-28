from __future__ import annotations

import json
import random
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from ai import make_bot
from engine import Outcome, PlayerId
from server.app import app, store
from tests.strategies import coordinates_in

EXACT_KINDS = ("ACTIVE_FIX", "PING_DETECTED")


@pytest.fixture
def client() -> Iterator[TestClient]:
    store.clear()
    with TestClient(app) as test_client:
        yield test_client
    store.clear()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def start_match(client: TestClient) -> tuple[str, str, str]:
    created = client.post("/matches").json()
    joined = client.post(f"/matches/{created['match_id']}/join").json()
    return created["match_id"], created["token"], joined["token"]


def act(client: TestClient, match_id: str, token: str, **body: object):
    return client.post(f"/matches/{match_id}/action", json=body, headers=auth(token))


def view_of(client: TestClient, match_id: str, token: str) -> dict:
    response = client.get(f"/matches/{match_id}/view", headers=auth(token))
    assert response.status_code == 200
    return response.json()


# --- Creating and joining --------------------------------------------------


def test_creating_a_match_returns_201_with_a_seat(client: TestClient) -> None:
    response = client.post("/matches")

    assert response.status_code == 201
    body = response.json()
    assert body["player_id"] == "P1"
    assert body["token"]
    assert body["view"]["round"] == 1
    assert body["view"]["outcome"] == "ONGOING"


def test_joining_returns_200_and_the_second_seat(client: TestClient) -> None:
    match_id = client.post("/matches").json()["match_id"]

    response = client.post(f"/matches/{match_id}/join")

    assert response.status_code == 200
    assert response.json()["player_id"] == "P2"


def test_joining_a_full_match_is_409(client: TestClient) -> None:
    match_id, _, _ = start_match(client)

    response = client.post(f"/matches/{match_id}/join")

    assert response.status_code == 409
    assert response.json()["error"] == "match_full"


def test_joining_an_unknown_match_is_404(client: TestClient) -> None:
    response = client.post("/matches/not-a-real-code/join")

    assert response.status_code == 404
    assert response.json()["error"] == "match_not_found"


def test_match_ids_are_unguessable_and_not_sequential(client: TestClient) -> None:
    ids = [client.post("/matches").json()["match_id"] for _ in range(50)]

    assert len(set(ids)) == 50
    assert all(len(match_id) >= 22 for match_id in ids)
    assert not any(match_id.isdigit() for match_id in ids)
    assert all(a[:8] != b[:8] for a, b in zip(ids, ids[1:]))


def test_the_two_players_get_different_tokens(client: TestClient) -> None:
    _, token_p1, token_p2 = start_match(client)

    assert token_p1 != token_p2


# --- Auth ------------------------------------------------------------------


def test_a_request_without_a_token_is_401(client: TestClient) -> None:
    match_id, _, _ = start_match(client)

    response = client.get(f"/matches/{match_id}/view")

    assert response.status_code == 401
    assert response.json()["error"] == "missing_token"


def test_a_malformed_authorization_header_is_401(client: TestClient) -> None:
    match_id, token, _ = start_match(client)

    response = client.get(
        f"/matches/{match_id}/view", headers={"Authorization": token}
    )

    assert response.status_code == 401


def test_a_token_from_another_match_is_403(client: TestClient) -> None:
    first, token_of_first, _ = start_match(client)
    second, _, _ = start_match(client)

    response = client.get(
        f"/matches/{second}/view", headers=auth(token_of_first)
    )

    assert response.status_code == 403
    assert response.json()["error"] == "invalid_token"


def test_an_unknown_match_is_404(client: TestClient) -> None:
    _, token, _ = start_match(client)

    response = client.get("/matches/nope/view", headers=auth(token))

    assert response.status_code == 404


# --- The architectural centrepiece: the view is token-scoped ---------------


def test_each_token_gets_its_own_ship_and_only_its_own(client: TestClient) -> None:
    match_id, token_p1, token_p2 = start_match(client)
    truth = store.get(match_id).state.ships

    view_p1 = view_of(client, match_id, token_p1)
    view_p2 = view_of(client, match_id, token_p2)

    assert view_p1["your_ship"]["position"] == list(truth[PlayerId.P1].position)
    assert view_p2["your_ship"]["position"] == list(truth[PlayerId.P2].position)


def test_the_view_has_exactly_the_keys_the_prd_specifies(client: TestClient) -> None:
    match_id, token, _ = start_match(client)

    assert set(view_of(client, match_id, token)) == {
        "round",
        "phase",
        "your_ship",
        "contacts",
        "last_result",
        "opponent_status",
        "outcome",
    }


def test_no_response_body_ever_carries_the_opponents_cell(client: TestClient) -> None:
    match_id, token_p1, token_p2 = start_match(client)

    for _ in range(12):
        record = store.get(match_id)
        if record.state.outcome is not Outcome.ONGOING:
            break

        act(client, match_id, token_p1, type="PING")
        act(client, match_id, token_p2, type="MOVE", direction="NE")

        for token, player in ((token_p1, PlayerId.P1), (token_p2, PlayerId.P2)):
            body = view_of(client, match_id, token)
            record = store.get(match_id)
            own = record.state.ships[player].position
            enemy = record.state.ships[player.other].position
            granted = {
                tuple(contact["exact_position"])
                for contact in body["contacts"]
                if contact["kind"] in EXACT_KINDS
            }

            assert set(coordinates_in(body)) <= {own} | granted
            if enemy not in granted and enemy != own:
                assert enemy not in coordinates_in(body)


def test_a_raw_game_state_is_never_serialized(client: TestClient) -> None:
    match_id, token_p1, token_p2 = start_match(client)
    act(client, match_id, token_p1, type="MOVE", direction="N")
    act(client, match_id, token_p2, type="PING")

    for token in (token_p1, token_p2):
        body = json.dumps(view_of(client, match_id, token))
        for leaked in ("rng_seed", "ships", "P1", "P2", "last_events"):
            assert leaked not in body


# --- Submitting actions ----------------------------------------------------


def test_a_submitted_action_is_held_until_both_players_have_acted(
    client: TestClient,
) -> None:
    match_id, token_p1, token_p2 = start_match(client)

    first = act(client, match_id, token_p1, type="RUN_SILENT")
    assert first.status_code == 200
    assert first.json() == {"round": 1, "phase": "AWAITING_ACTIONS"}
    assert store.get(match_id).state.round == 1

    second = act(client, match_id, token_p2, type="RUN_SILENT")
    assert second.status_code == 200
    assert second.json() == {"round": 2, "phase": "RESOLVED"}
    assert store.get(match_id).state.round == 2


def test_a_second_action_in_the_same_round_is_409(client: TestClient) -> None:
    match_id, token_p1, _ = start_match(client)
    act(client, match_id, token_p1, type="RUN_SILENT")

    response = act(client, match_id, token_p1, type="PING")

    assert response.status_code == 409
    assert response.json()["error"] == "already_acted"


def test_a_retried_identical_action_does_not_double_apply(
    client: TestClient,
) -> None:
    match_id, token_p1, _ = start_match(client)
    act(client, match_id, token_p1, type="MOVE", direction="N")

    retry = act(client, match_id, token_p1, type="MOVE", direction="N")

    assert retry.status_code == 409
    assert store.get(match_id).pending[PlayerId.P1].direction == "N"
    assert len(store.get(match_id).pending) == 1


@pytest.mark.parametrize(
    ("body", "expected_error"),
    [
        ({"type": "FIRE"}, "target_required"),
        ({"type": "MOVE"}, "direction_required"),
        ({"type": "MOVE", "direction": "UP"}, "invalid_direction"),
        ({"type": "FIRE", "target": [99, 0]}, "target_out_of_bounds"),
        ({"type": "FIRE", "target": [-1, 4]}, "target_out_of_bounds"),
    ],
)
def test_a_malformed_action_is_400_with_a_structured_body(
    client: TestClient, body: dict, expected_error: str
) -> None:
    match_id, token_p1, _ = start_match(client)

    response = act(client, match_id, token_p1, **body)

    assert response.status_code == 400
    assert response.json()["error"] == expected_error
    assert response.json()["detail"]


def test_an_unknown_action_type_is_400(client: TestClient) -> None:
    match_id, token_p1, _ = start_match(client)

    response = act(client, match_id, token_p1, type="TELEPORT")

    assert response.status_code == 400
    assert response.json()["error"] == "malformed_request"


def test_acting_after_the_match_has_ended_is_409(client: TestClient) -> None:
    match_id, token_p1, token_p2 = start_match(client)
    client.post(f"/matches/{match_id}/resign", headers=auth(token_p2))

    response = act(client, match_id, token_p1, type="PING")

    assert response.status_code == 409
    assert response.json()["error"] == "match_over"


# --- Resign ----------------------------------------------------------------


def test_resigning_hands_the_win_to_the_opponent(client: TestClient) -> None:
    match_id, token_p1, token_p2 = start_match(client)

    response = client.post(f"/matches/{match_id}/resign", headers=auth(token_p1))

    assert response.status_code == 200
    assert response.json()["outcome"] == "LOSS"
    assert view_of(client, match_id, token_p2)["outcome"] == "WIN"


def test_resigning_twice_is_409(client: TestClient) -> None:
    match_id, token_p1, _ = start_match(client)
    client.post(f"/matches/{match_id}/resign", headers=auth(token_p1))

    response = client.post(f"/matches/{match_id}/resign", headers=auth(token_p1))

    assert response.status_code == 409


# --- History ---------------------------------------------------------------


def test_history_is_refused_while_the_match_is_live(client: TestClient) -> None:
    match_id, token_p1, _ = start_match(client)

    response = client.get(f"/matches/{match_id}/history", headers=auth(token_p1))

    assert response.status_code == 409
    assert response.json()["error"] == "match_in_progress"


def test_history_needs_a_token_too(client: TestClient) -> None:
    match_id, _, _ = start_match(client)

    assert client.get(f"/matches/{match_id}/history").status_code == 401


def test_history_is_the_defogged_record_once_the_match_is_over(
    client: TestClient,
) -> None:
    match_id, token_p1, token_p2 = start_match(client)
    act(client, match_id, token_p1, type="MOVE", direction="N")
    act(client, match_id, token_p2, type="PING")
    client.post(f"/matches/{match_id}/resign", headers=auth(token_p1))

    body = client.get(f"/matches/{match_id}/history", headers=auth(token_p1)).json()

    assert body["outcome"] == "P2_WINS"
    assert len(body["rounds"]) == 1
    entry = body["rounds"][0]
    assert entry["actions"]["P1"] == {"type": "MOVE", "direction": "N"}
    assert entry["actions"]["P2"] == {"type": "PING"}
    assert set(entry["ships_after"]) == {"P1", "P2"}
    assert set(body["final_positions"]) == {"P1", "P2"}


# --- Solo play against a bot ----------------------------------------------


def test_creating_a_solo_match_seats_a_bot(client: TestClient) -> None:
    response = client.post("/matches", json={"opponent": "ai", "level": 4})

    assert response.status_code == 201
    assert response.json()["opponent"] == "Hunter"
    assert response.json()["player_id"] == "P1"


def test_a_solo_match_cannot_be_joined(client: TestClient) -> None:
    """The second seat is taken, even though no token was ever issued for it."""
    match_id = client.post("/matches", json={"opponent": "ai"}).json()["match_id"]

    response = client.post(f"/matches/{match_id}/join")

    assert response.status_code == 409
    assert response.json()["error"] == "match_full"


def test_a_solo_round_resolves_on_the_humans_action_alone(client: TestClient) -> None:
    created = client.post("/matches", json={"opponent": "ai", "level": 1}).json()
    match_id, token = created["match_id"], created["token"]

    response = act(client, match_id, token, type="RUN_SILENT")

    assert response.status_code == 200
    assert response.json() == {"round": 2, "phase": "RESOLVED"}


def test_the_bot_cannot_see_the_humans_action_for_the_same_round(
    client: TestClient,
) -> None:
    """Simultaneity, tested rather than asserted.

    Two matches are forced into an identical position with identically seeded
    bots, then the human does something completely different in each. If the
    bot's own move is the same both times, it cannot have been influenced by
    what the human submitted in that round.
    """
    first = client.post("/matches", json={"opponent": "ai", "level": 3}).json()
    second = client.post("/matches", json={"opponent": "ai", "level": 3}).json()

    record_a, record_b = store.get(first["match_id"]), store.get(second["match_id"])
    record_b.state = record_a.state
    record_a.opponent = make_bot(3, random.Random(99))
    record_b.opponent = make_bot(3, random.Random(99))

    act(client, first["match_id"], first["token"], type="MOVE", direction="N")
    act(client, second["match_id"], second["token"], type="FIRE", target=[0, 0])

    assert (
        record_a.history[0].actions[PlayerId.P2]
        == record_b.history[0].actions[PlayerId.P2]
    )


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5])
def test_every_level_can_be_played_to_a_conclusion_over_http(
    client: TestClient, level: int
) -> None:
    created = client.post("/matches", json={"opponent": "ai", "level": level}).json()
    match_id, token = created["match_id"], created["token"]

    for _ in range(60):
        if view_of(client, match_id, token)["outcome"] != "ONGOING":
            break
        assert act(client, match_id, token, type="PING").status_code == 200

    assert view_of(client, match_id, token)["outcome"] in ("WIN", "LOSS", "DRAW")
    assert (
        client.get(f"/matches/{match_id}/history", headers=auth(token)).status_code
        == 200
    )


@pytest.mark.parametrize("level", [0, 6, -1])
def test_an_out_of_range_level_is_400(client: TestClient, level: int) -> None:
    response = client.post("/matches", json={"opponent": "ai", "level": level})

    assert response.status_code == 400
    assert response.json()["error"] == "malformed_request"


def test_creating_a_match_without_a_body_still_means_a_human_opponent(
    client: TestClient,
) -> None:
    response = client.post("/matches")

    assert response.status_code == 201
    assert response.json()["opponent"] == "human"


def test_a_solo_view_never_leaks_the_bots_position(client: TestClient) -> None:
    created = client.post("/matches", json={"opponent": "ai", "level": 5}).json()
    match_id, token = created["match_id"], created["token"]

    for _ in range(10):
        if view_of(client, match_id, token)["outcome"] != "ONGOING":
            break
        act(client, match_id, token, type="MOVE", direction="E")

        body = view_of(client, match_id, token)
        record = store.get(match_id)
        own = record.state.ships[PlayerId.P1].position
        enemy = record.state.ships[PlayerId.P2].position
        granted = {
            tuple(contact["exact_position"])
            for contact in body["contacts"]
            if contact["kind"] in EXACT_KINDS
        }

        assert set(coordinates_in(body)) <= {own} | granted
        if enemy not in granted and enemy != own:
            assert enemy not in coordinates_in(body)


# --- A whole match over HTTP ----------------------------------------------


def test_two_clients_can_play_a_match_to_a_conclusion(client: TestClient) -> None:
    match_id, token_p1, token_p2 = start_match(client)

    for _ in range(60):
        if store.get(match_id).state.outcome is not Outcome.ONGOING:
            break
        assert act(client, match_id, token_p1, type="PING").status_code == 200
        assert (
            act(client, match_id, token_p2, type="MOVE", direction="SW").status_code
            == 200
        )

    final_p1 = view_of(client, match_id, token_p1)
    final_p2 = view_of(client, match_id, token_p2)

    assert final_p1["outcome"] != "ONGOING"
    assert {final_p1["outcome"], final_p2["outcome"]} in (
        {"WIN", "LOSS"},
        {"DRAW"},
    )
    assert client.get(
        f"/matches/{match_id}/history", headers=auth(token_p1)
    ).status_code == 200


def test_a_player_who_stops_polling_and_resumes_misses_nothing(
    client: TestClient,
) -> None:
    match_id, token_p1, token_p2 = start_match(client)

    for _ in range(3):
        act(client, match_id, token_p1, type="RUN_SILENT")
        act(client, match_id, token_p2, type="RUN_SILENT")

    resumed = view_of(client, match_id, token_p2)

    assert resumed["round"] == 4
    assert resumed["outcome"] == "ONGOING"
