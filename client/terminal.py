from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import httpx

from config import DEFAULT

BUCKETS = {"CLOSE": "close", "MEDIUM": "medium", "FAR": "far"}
HELP = "  s = run silent | m <DIR> = move | p = ping | f <x> <y> = fire | q = resign"


def describe(contact: dict[str, Any]) -> str:
    kind = contact["kind"].replace("_", " ").lower()
    if contact["exact_position"] is not None:
        x, y = contact["exact_position"]
        return f"{kind}: exact fix at ({x},{y})"
    return (
        f"{kind}: {contact['bearing_deg']:.1f} deg, "
        f"{BUCKETS[contact['range_bucket']]}"
    )


def render(view: dict[str, Any]) -> str:
    x, y = view["your_ship"]["position"]
    lines = [
        "",
        f"round {view['round']}  [{view['phase']}]",
        f"  you: ({x},{y})  hull {view['your_ship']['hull']}",
    ]

    result = view["last_result"]
    if result is not None:
        if result["you_hit_enemy"]:
            lines.append("  >> your torpedo connected")
        if result["you_were_hit"]:
            lines.append("  >> you were hit")

    if view["contacts"]:
        lines.extend("  * " + describe(contact) for contact in view["contacts"])
    else:
        lines.append("  * no contacts")
    return "\n".join(lines)


def parse_action(line: str) -> dict[str, Any] | None:
    parts = line.strip().split()
    if not parts:
        return None

    head = parts[0].lower()
    if head in ("s", "silent") and len(parts) == 1:
        return {"type": "RUN_SILENT"}
    if head in ("p", "ping") and len(parts) == 1:
        return {"type": "PING"}
    if head in ("m", "move") and len(parts) == 2:
        return {"type": "MOVE", "direction": parts[1].upper()}
    if head in ("f", "fire") and len(parts) == 3:
        try:
            return {"type": "FIRE", "target": [int(parts[1]), int(parts[2])]}
        except ValueError:
            return None
    return None


def prompt() -> dict[str, Any] | None:
    while True:
        try:
            line = input("action> ")
        except EOFError:
            return None
        if line.strip().lower() in ("q", "resign"):
            return None

        action = parse_action(line)
        if action is not None:
            return action
        print(HELP)


def submit_turn(
    client: httpx.Client, match_id: str, headers: dict[str, str]
) -> bool:
    while True:
        action = prompt()
        if action is None:
            client.post(f"/matches/{match_id}/resign", headers=headers)
            return False

        response = client.post(
            f"/matches/{match_id}/action", json=action, headers=headers
        )
        if response.status_code == 200:
            return True
        print(f"  rejected: {response.json().get('detail', response.text)}")


def wait_for_round(
    client: httpx.Client, match_id: str, headers: dict[str, str], acted_round: int
) -> dict[str, Any]:
    print("  waiting for your opponent", end="", flush=True)
    while True:
        view = client.get(f"/matches/{match_id}/view", headers=headers).json()
        if view["round"] != acted_round or view["outcome"] != "ONGOING":
            print()
            return view
        print(".", end="", flush=True)
        time.sleep(DEFAULT.poll_interval_s)


def play(base_url: str, join_code: str | None, solo_level: int | None = None) -> int:
    with httpx.Client(base_url=base_url, timeout=15.0) as client:
        if join_code is not None:
            response = client.post(f"/matches/{join_code}/join")
        elif solo_level is not None:
            response = client.post(
                "/matches", json={"opponent": "ai", "level": solo_level}
            )
        else:
            response = client.post("/matches")

        if response.status_code not in (200, 201):
            print(f"could not start: {response.json().get('detail', response.text)}")
            return 1

        seat = response.json()
        match_id = seat["match_id"]
        headers = {"Authorization": f"Bearer {seat['token']}"}
        view = seat["view"]

        print(f"\nyou are {seat['player_id']}")
        if seat.get("opponent", "human") != "human":
            print(f"opponent: {seat['opponent']} (level {solo_level})")
        elif join_code is None:
            print(f"share this join code:\n\n  {match_id}\n")
        print(HELP)

        while True:
            print(render(view))
            if view["outcome"] != "ONGOING":
                print(f"\n=== {view['outcome']} ===\n")
                return 0

            acted_round = view["round"]
            if not submit_turn(client, match_id, headers):
                view = client.get(
                    f"/matches/{match_id}/view", headers=headers
                ).json()
                continue
            view = wait_for_round(client, match_id, headers, acted_round)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="silent-running")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    seat = parser.add_mutually_exclusive_group()
    seat.add_argument("--join", metavar="CODE", default=None)
    seat.add_argument(
        "--solo",
        type=int,
        metavar="LEVEL",
        choices=range(1, 6),
        default=None,
        help="play a bot: 1 Drifter, 2 Reactor, 3 Tracker, 4 Hunter, 5 Ghost",
    )
    args = parser.parse_args(argv)

    try:
        return play(args.server, args.join, args.solo)
    except KeyboardInterrupt:
        print("\nbye")
        return 130
    except httpx.HTTPError as error:
        print(f"network error: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
