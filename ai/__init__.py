"""AI opponents. Headless clients — nothing more.

A bot receives exactly the same fogged ``PlayerView`` a human would and returns
exactly one ``Action`` per round. It has no ``GameState`` access, no privileged
sensor, and no sight of the enemy's true position.

Difficulty is therefore never a matter of *information*, only of inference
quality: Drifter, Reactor, Tracker, Hunter, Ghost. A bot that could see through
the fog would violate the property this whole project exists to prove, so the
leak-invariant test covers the bots for free.
"""
