from __future__ import annotations

from collections import Counter

from config import DEFAULT, GameConfig
from engine import DIRECTION_VECTORS, Coord
from engine.geometry import clamp_to_grid, euclidean_distance, on_grid
from perception import PlayerView, bearing_sigma_deg, range_bucket, true_bearing_deg

from ai.base import EXACT_KINDS, angular_gap

TOLERANCE_SIGMAS = 2.5


class Belief:
    """The cells the enemy could plausibly occupy, narrowed by each round's contacts.

    Built only from PlayerViews. It knows the published sensor model - the noise
    formula and the bucket boundaries are rules, not secrets - but never a
    position it was not told.
    """

    def __init__(self, config: GameConfig = DEFAULT) -> None:
        self.config = config
        self.cells: set[Coord] = {
            (x, y) for x in range(config.grid_size) for y in range(config.grid_size)
        }

    @property
    def size(self) -> int:
        return len(self.cells)

    @property
    def is_pinned(self) -> bool:
        """True when exactly one cell remains, which only an exact fix achieves."""
        return len(self.cells) == 1

    def advance(self, view: PlayerView) -> None:
        """Age the belief by one round, then narrow it with what this round revealed."""
        self.cells = self.spread(self.cells)
        self._observe(view)

    def spread(self, cells: set[Coord]) -> set[Coord]:
        """Every cell reachable from `cells` in one round: staying, or a full Move."""
        reachable: set[Coord] = set()
        for x, y in cells:
            reachable.add((x, y))
            for dx, dy in DIRECTION_VECTORS.values():
                reachable.add(
                    (
                        clamp_to_grid(
                            x + dx * self.config.move_distance, self.config.grid_size
                        ),
                        clamp_to_grid(
                            y + dy * self.config.move_distance, self.config.grid_size
                        ),
                    )
                )
        return reachable

    def after_their_move(self) -> set[Coord]:
        """Where a dodge could land them next round."""
        return self.spread(self.cells)

    def confirm_hit(self, target: Coord) -> None:
        """A torpedo that connected proves they were inside its blast.

        Sharper than any bearing: the blast footprint is nine cells with no
        noise on it at all. Only worth anything when a ship survives a hit,
        which is why nothing used this while a single blast ended the match.
        """
        radius = self.config.blast_radius
        footprint = {
            (target[0] + dx, target[1] + dy)
            for dx in range(-radius, radius + 1)
            for dy in range(-radius, radius + 1)
            if on_grid((target[0] + dx, target[1] + dy), self.config)
        }
        self.cells = (self.cells & footprint) or footprint

    def centroid(self) -> Coord:
        """The belief's centre of mass, as a single best guess."""
        count = len(self.cells)
        return (
            round(sum(cell[0] for cell in self.cells) / count),
            round(sum(cell[1] for cell in self.cells) / count),
        )

    def uniform_weights(self) -> Counter[Coord]:
        """Equal weight on every believed cell: assumes the enemy stays put."""
        return Counter({cell: 1.0 for cell in self.cells})

    def dodge_weights(self, stay_chance: float) -> Counter[Coord]:
        """Weight over where the enemy will be next round, given a chance they hold.

        Only a Move relocates a ship - Ping, Fire and Run Silent all leave it
        where it is - so a model that assumes the enemy always dodges is as
        wrong as one that assumes they never do. ``stay_chance`` is the share of
        the weight left on the cell they already occupy.
        """
        weights: Counter[Coord] = Counter()
        moving = (1.0 - stay_chance) / len(DIRECTION_VECTORS)

        for x, y in self.cells:
            weights[(x, y)] += stay_chance
            for dx, dy in DIRECTION_VECTORS.values():
                weights[
                    (
                        clamp_to_grid(
                            x + dx * self.config.move_distance, self.config.grid_size
                        ),
                        clamp_to_grid(
                            y + dy * self.config.move_distance, self.config.grid_size
                        ),
                    )
                ] += moving
        return weights

    def best_shot(self, weights: Counter[Coord] | None = None) -> tuple[Coord, float]:
        """The best cell to fire at, and the chance its blast catches the enemy.

        The second value is what lets a bot decide whether a shot is worth
        taking at all, rather than firing whenever the belief happens to fall
        below some arbitrary size.

        Coverage is accumulated by walking each cell's footprint once rather
        than scoring every candidate against every cell, so this stays linear in
        the size of the belief instead of quadratic.
        """
        scored = self.uniform_weights() if weights is None else weights
        radius = self.config.blast_radius
        coverage: Counter[Coord] = Counter()

        for (x, y), weight in scored.items():
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    candidate = (x + dx, y + dy)
                    if on_grid(candidate, self.config):
                        coverage[candidate] += weight

        total = sum(scored.values())
        if not coverage or total <= 0.0:
            return self.centroid(), 0.0

        # Ties are common - every cell whose blast catches a lone believed cell
        # scores the same - so break them toward the middle of the weight. That
        # keeps the aim point where the next round's evidence is likeliest to
        # still be useful, and makes the choice reproducible.
        best_score = max(coverage.values())
        centre_x = sum(x * w for (x, _), w in scored.items()) / total
        centre_y = sum(y * w for (_, y), w in scored.items()) / total
        tied = sorted(cell for cell, score in coverage.items() if score == best_score)
        best = min(
            tied,
            key=lambda cell: ((cell[0] - centre_x) ** 2 + (cell[1] - centre_y) ** 2, cell),
        )
        return best, best_score / total

    def best_blast(self, weights: Counter[Coord] | None = None) -> Coord:
        """The cell whose blast covers the most of the belief."""
        return self.best_shot(weights)[0]

    def _observe(self, view: PlayerView) -> None:
        # A quiet round rules nothing out: Run Silent is always available, so
        # silence is equally consistent with a ship that moved beyond passive
        # range and one that sat still. Only contacts ever narrow the belief.
        own = view.your_ship.position

        for contact in view.contacts:
            if contact.kind in EXACT_KINDS and contact.exact_position is not None:
                self.cells = {contact.exact_position}
                return

        for contact in view.contacts:
            if contact.bearing_deg is None or contact.range_bucket is None:
                continue
            narrowed = self._cone(own, contact.bearing_deg, contact.range_bucket)
            if narrowed:
                self.cells = narrowed
            return

    def _cone(self, own: Coord, bearing_deg: float, bucket: str) -> set[Coord]:
        """Cells consistent with a noised bearing and its coarse range bucket."""
        kept: set[Coord] = set()
        for cell in self.cells:
            distance = euclidean_distance(own, cell)
            if range_bucket(distance, self.config) != bucket:
                continue
            if distance == 0.0:
                kept.add(cell)
                continue

            sigma = bearing_sigma_deg(distance, self.config)
            gap = angular_gap(true_bearing_deg(own, cell), bearing_deg)
            if gap <= TOLERANCE_SIGMAS * sigma:
                kept.add(cell)
        return kept
