"""Terminal client. Consumes a ``PlayerView``, renders it, submits one action.

It polls ``GET /matches/{id}/view``, watches the ``round`` field to notice when a
round has resolved, draws the radar, and POSTs the captain's choice.

It has no access to ``GameState``. It cannot cheat because it is never sent the
enemy's position — not because it politely declines to look.
"""
