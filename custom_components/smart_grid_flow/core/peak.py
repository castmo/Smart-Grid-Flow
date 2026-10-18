"""Effekttariff: följ månadens högsta timmedeleffekter (olika dygn)."""
from __future__ import annotations

from datetime import datetime
from typing import Any


class PeakTracker:
    """Håller högsta timeffekt per dygn för innevarande månad."""

    def __init__(self, top_n: int = 3) -> None:
        self.top_n = top_n
        self.month: str = ""
        self.day_max: dict[str, float] = {}  # "ÅÅÅÅ-MM-DD" -> kW

    def add_hour(self, hour_start: datetime, kw: float) -> None:
        month = hour_start.strftime("%Y-%m")
        if month != self.month:
            self.month = month
            self.day_max = {}
        day = hour_start.strftime("%Y-%m-%d")
        if kw > self.day_max.get(day, 0.0):
            self.day_max[day] = round(kw, 3)

    def top(self) -> list[float]:
        return sorted(self.day_max.values(), reverse=True)[: self.top_n]

    def threshold(self, now: datetime | None = None) -> float:
        """Effekt som en enskild timme måste överstiga för att höja avgiften.

        Så länge det finns färre än N toppar är varje ny timme en topp (0).
        """
        if now is not None and now.strftime("%Y-%m") != self.month:
            return 0.0
        top = self.top()
        if len(top) < self.top_n:
            return 0.0
        return top[-1]

    def billed_kw(self) -> float:
        top = self.top()
        return sum(top) / len(top) if top else 0.0

    def cost(self, price_kr_kw: float) -> float:
        return self.billed_kw() * price_kr_kw

    def to_dict(self) -> dict[str, Any]:
        return {"month": self.month, "day_max": self.day_max}

    def load(self, d: dict[str, Any]) -> None:
        self.month = d.get("month", "")
        self.day_max = {k: float(v) for k, v in d.get("day_max", {}).items()}


class HourAccumulator:
    """Integrerar effekt (W) eller energimätare (kWh) till kWh per timme."""

    def __init__(self) -> None:
        self.hour: datetime | None = None
        self.kwh = 0.0
        self._last_t: datetime | None = None
        self._last_w: float | None = None
        self._counter_start: float | None = None

    def feed_power(self, now: datetime, watts: float) -> tuple[datetime, float] | None:
        """Returnerar (timmens start, kWh) när en timme avslutats."""
        done = self._roll(now)
        if self._last_t is not None and self._last_w is not None:
            dt_h = (now - self._last_t).total_seconds() / 3600.0
            self.kwh += self._last_w / 1000.0 * min(dt_h, 0.25)
        self._last_t, self._last_w = now, watts
        return done

    def feed_counter(self, now: datetime, kwh_total: float) -> tuple[datetime, float] | None:
        done = self._roll(now, counter=kwh_total)
        if self._counter_start is None:
            self._counter_start = kwh_total
        self.kwh = max(kwh_total - self._counter_start, 0.0)
        return done

    def _roll(self, now: datetime, counter: float | None = None):
        h = now.replace(minute=0, second=0, microsecond=0)
        done = None
        if self.hour is None:
            self.hour = h
        elif h != self.hour:
            done = (self.hour, self.kwh)
            self.hour = h
            self.kwh = 0.0
            self._counter_start = counter
        return done
