"""HTTP transport. FastAPI routing, tokens, serialization — and no game rules.

This layer creates and joins matches, holds the in-memory match store, collects
both players' actions, calls ``engine.resolve`` when the round is complete, and
serializes whatever ``perception.view_for`` hands back.

It decides *who is asking*, never *what is true*. If a rule of the game is being
decided here, it is in the wrong layer.

The auth boundary and the hidden-state boundary are the same boundary: the token
that authenticates a request is also what scopes the view it receives, so there
is no code path by which a player can request the opponent's view.
"""
