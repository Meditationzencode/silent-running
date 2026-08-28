from dataclasses import dataclass


@dataclass(frozen=True)
class GameConfig:
    grid_size: int = 25
    move_distance: int = 2
    ping_range: float = 12.0
    passive_range: float = 18.0
    bucket_close_max: float = 6.0
    bucket_medium_max: float = 12.0
    bearing_base_err_deg: float = 4.0
    bearing_err_per_cell_deg: float = 0.6
    blast_radius: int = 1
    hull: int = 2
    round_cap: int = 50
    turn_timeout_s: float = 90.0
    poll_interval_s: float = 1.0


DEFAULT = GameConfig()
