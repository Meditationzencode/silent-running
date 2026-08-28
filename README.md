# Silent Running

> Two blind hunters in the dark. To find your enemy, you must risk being found.

A two-player, hidden-information strategy game played over a REST API in the terminal.
Chess's structure — discrete turns, an authoritative server, no reflexes — with one rule
flipped: **you cannot see your opponent.**

The interesting problem here isn't the networking. It's that the server holds the only
copy of the truth and must hand each player a deliberately degraded view of it, without
ever leaking the rest. That property is enforced in one place, and proven by a
property-based test that runs against the exact bytes an endpoint returns.

---

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Then play a bot in one terminal:

```bash
python -m client.terminal --solo 3        # 1 Drifter … 5 Ghost
```

or a friend, in two:

```bash
python -m client.terminal                 # prints a join code
python -m client.terminal --join <code>   # the other player
```

## Playing

Each round both captains secretly choose one action, and the server resolves both at
once. Every action trades information for exposure:

| Action | You gain | You leak |
|---|---|---|
| **Run Silent** | a bearing on them, *if* they emitted | nothing — you are invisible this round |
| **Move** | reposition 2 cells | a heat signature: noisy bearing + coarse range |
| **Ping** | their exact cell, if within 12 | your exact cell, always, at any range |
| **Fire** | a 3×3 blast on any cell you name | a launch signature, same as a Move |

A ping outside range tells you nothing and still announces exactly where you are.

A real match against Hunter, abridged:

```
round 3  [RESOLVED]
  you: (11,4)  hull 1
  * passive bearing: 18.4 deg, medium
action> p

round 4  [RESOLVED]
  you: (11,4)  hull 1
  * active fix: exact fix at (18,11)
action> m SW

round 6  [RESOLVED]
  you: (9,2)  hull 0
  >> you were hit
  * launch detected: 30.6 deg, far

=== LOSS ===
```

The ping in round 3 bought an exact position and sold one. Two rounds later the bot put
a torpedo through the cell that ping had lit up. That trade is the whole game.

---

## The property this is built around

The enemy's true position is a field of `GameState` and never a field of any
`PlayerView`. The only way an exact enemy cell reaches a player is inside a `Contact` of
kind `ACTIVE_FIX` (you pinged, they were in range) or `PING_DETECTED` (they pinged) —
the two cases where the sensor rules legitimately grant it.

That claim is asserted with Hypothesis across 2,000 generated states and action pairs
per run, against the serialized response body rather than against Python objects:

```python
new_state, _ = resolve(state, action_p1, action_p2, random.Random(seed))

for player in (PlayerId.P1, PlayerId.P2):
    view = view_for(new_state, player, random.Random(seed))
    payload = json.loads(json.dumps(to_payload(view)))   # exactly what the endpoint sends

    own = new_state.ships[player].position
    granted = {c.exact_position for c in view.contacts if c.kind in EXACT_KINDS}

    # Every fix was earned: a PING_DETECTED only if they really pinged, an
    # ACTIVE_FIX only if you pinged and they really were inside PING_RANGE.
    for contact in view.contacts:
        if contact.kind == "ACTIVE_FIX":
            assert player in pingers
            assert euclidean_distance(own, enemy) <= DEFAULT.ping_range

    # The only coordinates on the wire are your own cell and earned fixes.
    assert set(coordinates_in(payload)) <= {own} | granted
```

Two details make this stronger than it first looks.

**It checks that each fix was earned.** The obvious version of this test asks "does a
legitimate fix exist, and if so, is the cell allowed?" — which a broken `view_for` that
attached an `ACTIVE_FIX` to every view would pass while leaking on every round. This
version recomputes who actually pinged from the engine's emission record and re-checks
the range gate independently, so the view has to agree with the round that produced it.

**It has been watched failing.** A passing property test proves nothing until you have
seen it fail, so the fog was deliberately sabotaged four ways: an unearned `ACTIVE_FIX`,
a fix granted beyond ping range, an exact cell smuggled inside a degraded contact, and a
stray debug key added to the payload. The invariant caught all four.

It also found a real bug on its first run: bearings were wrapped to `[0, 360)` and *then*
rounded, so `359.97` became `360.0` — not a compass bearing.

---

## Architecture

Four layers, and the dependency arrow only points one way.

```
client / ai  ──►  server  ──►  perception  ──►  engine
 PlayerView       HTTP only     the fog filter    the rules
```

**`engine`** — every game rule, as pure functions. `resolve(state, a1, a2, rng)` applies
one simultaneous round in a fixed order: movement (clamped to the grid) → emissions at
post-move positions → torpedoes against those positions → the detection hook. No I/O, no
globals, deterministic given a seeded rng.

Two of the game's most-felt rules fall directly out of that ordering. Movement before
detonation means a ship that moves off a targeted cell survives and the torpedo hits
empty space. All detonations resolving before any damage is applied means a dying ship's
torpedo still arrives — mutual destruction is a draw, not a win for whoever was checked
first.

**`perception`** — `view_for(state, player, rng) -> PlayerView`, the single doorway
between the truth and a player. Every byte a player receives passes through it. Bearing
noise is Gaussian with `σ = 4° + 0.6°/cell`, so a contact at 5 cells is a fairly sharp
direction and one at 15 cells is barely a direction at all. To sharpen a bearing you
have to close the distance; closing means burning; burning means emitting.

**`server`** — FastAPI. Routing, tokens, serialization, and no game rules. It decides
*who is asking*, never *what is true*.

**`client` / `ai`** — consume a `PlayerView` and return an action. They cannot cheat, not
because they decline to look, but because they are never sent the enemy's position.

### The auth boundary is the hidden-state boundary

`GET /matches/{id}/view` takes no player parameter. The bearer token that authenticates
the request is the same thing that decides which view gets built, so there is no code
path by which a player can request the opponent's view — they cannot name one.

---

## Design decisions

**REST with polling, not WebSockets.** The game is inference, not reflex: a sensor
reading arriving a second late breaks nothing, because the round does not advance until
both players have committed. With latency irrelevant to correctness, the entire budget
goes to hidden-state integrity instead of real-time sync. Long-polling is the natural
next step if the "nothing yet" responses ever matter; WebSockets would only be right if
this went real-time.

**The response body is built in `perception`, not `server`.** The leak invariant is
asserted against `to_payload` output, so that dict has to be the dict the endpoint
actually returns. A second serializer in the transport layer would be an untested path to
the wire. It is written field-by-field rather than reflectively, so a future `PlayerView`
field cannot serialize itself into a response by accident.

**The noise rng is derived per round, not held as a live stream.** `view_for` takes an
rng, so a live stream would draw fresh noise on every `GET` — a bearing would wobble
every second while a client polled, and the fog could be averaged away by polling in a
loop. Deriving `Random("<seed>:<round>:<player>")` keeps a bearing fixed for as long as
the round lasts and the whole match reproducible from the seed alone. The seed never
leaves the server, so the noise cannot be replayed and subtracted back off.

**Match ids are 256-bit random tokens.** The id doubles as the join code and is the only
thing guarding a private match, so a sequential id would let anyone walk into someone
else's game.

**The code carries no comments or docstrings.** Reasoning lives in commit messages, which
record what was rejected as well as what was chosen and cannot drift out of sync with the
code. Decisions that are load-bearing and easy to break are guarded by named tests
instead — `test_a_ship_is_not_caught_in_its_own_blast` fails when someone reverses it; a
comment would only have hoped. `git log -p` is the design record.

---

## The opponents

Five levels, and the difficulty is never information. A bot receives exactly the fogged
`PlayerView` a human does and returns one action — so the leak invariant above already
proves no bot at any level can see through the fog. What separates them is how well they
infer, and how well they act on the inference.

| | | |
|---|---|---|
| 1 | **Drifter** | Moves and fires at random. Never pings. A warm body in the seat. |
| 2 | **Reactor** | Silent until it hears something, then moves and fires that way. Forgets immediately, so it never triangulates. |
| 3 | **Tracker** | Holds a belief over enemy cells, narrows it with each bearing, and fires when a blast would cover enough of it. |
| 4 | **Hunter** | Aims where a dodge will land rather than where they were, and moves off the cell its own ping just advertised. |
| 5 | **Ghost** | Knows Hunter runs when pinged, and drops a torpedo along the line of flight — covering both the cell they hold and the one they flee to. |

Measured over both seatings of 80 seeds, higher beats lower in every pairing:

| | vs Drifter | vs Reactor | vs Tracker | vs Hunter |
|---|---|---|---|---|
| **Reactor** | 96.7% | | | |
| **Tracker** | 95.6% | 56.6% | | |
| **Hunter** | 95.3% | 59.8% | 80.9% | |
| **Ghost** | 95.9% | 58.3% | 70.5% | 90.6% |

Tracker over Reactor is the thinnest step and it is not a tuning artefact — sweeping
Tracker's firing threshold across its whole useful range moves it only between 52% and
56%. A quiet counter-puncher is genuinely close to a belief tracker that moves every
round. Relatedly, silence is strong enough that letting Tracker run silent while blind
flipped Hunter-over-Tracker from 81% to 17%; Tracker keeps moving because not knowing
that is what should keep it below the levels above.

## Status

| | |
|---|---|
| Pure engine — rules, resolution, win conditions | built |
| Perception layer + leak invariant + determinism proof | built |
| REST API, six endpoints, token-scoped views | built |
| Terminal client — polling, actions, resign | built |
| Five AI opponents, playable over HTTP | built |
| Radar-style terminal UI | planned |
| Timeouts, disconnect grace, reconnection | planned |
| Public deployment | planned |

Two people can play a full match over HTTP today, or one person against any of the five
bots.

---

## Tests

```bash
pytest                          # 510 tests
pytest --cov --cov-report=term  # 100% line and branch on engine + perception
```

Coverage is scoped to `engine` and `perception` deliberately. If the transport layers
counted, a handful of thin route tests would inflate the number while the layers holding
the actual rules could rot.

The suite covers the engine's edge cases as a table (edge clamp, in-blast / edge-of-blast
/ just-outside, simultaneous double-KO, dodging out of a targeted cell), the sensor model
against the worked examples and its bucket boundaries, the leak invariant and determinism
as properties, and the HTTP surface with `TestClient` — every status code, token scoping,
and idempotency.

---

## API

Every request after the first carries `Authorization: Bearer <token>`.

| Method | Path | Purpose | Success |
|---|---|---|---|
| `POST` | `/matches` | Create a match; returns the join code, a token, and your first view | `201` |
| `POST` | `/matches/{id}/join` | Join by code | `200` |
| `GET` | `/matches/{id}/view` | Your fogged view. Poll this. | `200` |
| `POST` | `/matches/{id}/action` | Submit your one action for the round | `200` |
| `POST` | `/matches/{id}/resign` | Resign; opponent wins | `200` |
| `GET` | `/matches/{id}/history` | De-fogged record, once the match has ended | `200` |

Errors return `{"error": "...", "detail": "..."}` with `400` for a malformed action,
`401`/`403` for a missing or wrong token, `404` for an unknown match, and `409` for a
double submit, a full match, acting after the end, or requesting history mid-match.

Interactive docs are at `/docs` while the server is running.
