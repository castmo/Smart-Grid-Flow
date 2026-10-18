"""Schemaläggning av flyttbara laster (varmvattenberedare, framtida elbilsladdning).

Samma byggsten (`cheapest_hours`) återanvänds av alla laster som bara behöver
"X timmar någonstans inom fönstret".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .optimizer import Step


def cheapest_hours(steps: list[Step], n_hours: int, window: int = 24) -> set[datetime]:
    """De ``n_hours`` billigaste timmarna inom de första ``window`` timmarna."""
    pool = sorted(steps[:window], key=lambda s: (s.price, s.start))
    return {s.start for s in pool[: max(n_hours, 0)]}


@dataclass
class BoilerSettings:
    run_hours_per_day: int = 3
    min_temp: float = 45.0  # under detta värms alltid
    max_temp: float = 75.0  # över detta stängs alltid av
    legionella_days: int = 7  # 0 = av
    legionella_temp: float = 65.0


def boiler_decision(
    now: datetime,
    steps: list[Step],
    cfg: BoilerSettings,
    temp: float | None = None,
    days_since_hot: float | None = None,
) -> tuple[bool, str, set[datetime]]:
    """Returnerar (på?, anledning, valda timmar)."""
    chosen = cheapest_hours(steps, cfg.run_hours_per_day)
    if temp is not None and temp >= cfg.max_temp:
        return False, "max_temp", chosen
    if temp is not None and temp < cfg.min_temp:
        return True, "min_temp", chosen
    if (
        cfg.legionella_days > 0
        and days_since_hot is not None
        and days_since_hot >= cfg.legionella_days
    ):
        return True, "legionella", chosen
    cur = now.replace(minute=0, second=0, microsecond=0)
    return (cur in chosen), "schema", chosen
