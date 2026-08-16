"""Game rules. Pure, deterministic, no I/O.

Contract for everything in this package:

* No network, no filesystem, no printing, no mutable module globals.
* Deterministic given a seeded ``rng``, so the same inputs always produce the
  same output and every rule is reproducible in a test.
* Holds 100% of the game rules — movement, emissions, detonation, win checking.
  ``server`` contains none of them.

The engine consumes and produces ``GameState``, the full truth. ``GameState`` is
never serialized into a response body; see ``perception`` for the only thing
that is.
"""
