from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import httpx

from client.radar import CLEAR_SCREEN, Plot, render, supports_colour
from config import DEFAULT

MENU = """
  m <DIR>     move two cells   (N NE E SE S SW W NW)
  f <X> <Y>   fire a 3x3 blast centred on that cell
  p           ping  - exact fix if they are within 12, and they get yours
  s           run silent - hold position, listen, emit nothing
  q           resign
"""


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
        print(MENU)


def submit_turn(client: httpx.Client, match_id: str, headers: dict[str, str]) -> bool:
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


def open_seat(
    client: httpx.Client, join_code: str | None, solo_level: int | None
) -> httpx.Response:
    if join_code is not None:
        return client.post(f"/matches/{join_code}/join")
    if solo_level is not None:
        return client.post("/matches", json={"opponent": "ai", "level": solo_level})
    return client.post("/matches")


def opponent_label(seat: dict[str, Any], solo_level: int | None) -> str:
    """The one line of match identity worth keeping on screen after a redraw."""
    opponent = seat.get("opponent", "human")
    if opponent != "human":
        return f"vs {opponent}, level {solo_level}"
    return f"join code {seat['match_id']}"


def play(base_url: str, join_code: str | None, solo_level: int | None = None) -> int:
    colour = supports_colour()
    plot = Plot()

    with httpx.Client(base_url=base_url, timeout=15.0) as client:
        response = open_seat(client, join_code, solo_level)
        if response.status_code not in (200, 201):
            print(f"could not start: {response.json().get('detail', response.text)}")
            return 1

        seat = response.json()
        match_id = seat["match_id"]
        headers = {"Authorization": f"Bearer {seat['token']}"}
        view = seat["view"]
        banner = (
            f"  S I L E N T   R U N N I N G   -   you are {seat['player_id']}, "
            f"{opponent_label(seat, solo_level)}"
        )

        if not colour:
            print(f"\n{banner}")
            print(MENU)

        while True:
            plot.record(view)
            if colour:
                print(CLEAR_SCREEN, end="")
                print(banner)
            print(render(view, colour=colour, plot=plot))
            if view["outcome"] != "ONGOING":
                print()
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
