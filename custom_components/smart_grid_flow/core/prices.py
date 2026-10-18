"""Spotprishantering: tolka API-svar och slå ihop till timpriser."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .tariff import TariffConfig


@dataclass(frozen=True)
class PriceSlot:
    """Ett timpris. ``start`` är tidszonsmedveten, ``spot`` är SEK/kWh exkl. moms."""

    start: datetime
    spot: float


def floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def parse_elprisetjustnu(data: Iterable[dict[str, Any]]) -> list[PriceSlot]:
    """Tolka svar från https://www.elprisetjustnu.se/api/v1/prices/ÅÅÅÅ/MM-DD_SE3.json.

    Svaret kan vara i 15-minutersupplösning; vi tar medelvärdet per timme
    eftersom både effektavgift och styrning arbetar med timmar.
    """
    buckets: dict[datetime, list[float]] = {}
    for item in data:
        start = datetime.fromisoformat(item["time_start"])
        buckets.setdefault(floor_hour(start), []).append(float(item["SEK_per_kWh"]))
    return [
        PriceSlot(start=h, spot=sum(v) / len(v)) for h, v in sorted(buckets.items())
    ]


def merge_slots(*groups: Iterable[PriceSlot]) -> list[PriceSlot]:
    merged: dict[datetime, PriceSlot] = {}
    for group in groups:
        for slot in group:
            merged[slot.start.astimezone(timezone.utc)] = slot
    return [merged[k] for k in sorted(merged)]


def future_slots(slots: list[PriceSlot], now: datetime) -> list[PriceSlot]:
    """Slots från och med aktuell timme."""
    cur = floor_hour(now).astimezone(timezone.utc)
    return [s for s in slots if s.start.astimezone(timezone.utc) >= cur]


def slot_at(slots: list[PriceSlot], when: datetime) -> PriceSlot | None:
    target = floor_hour(when).astimezone(timezone.utc)
    for s in slots:
        if s.start.astimezone(timezone.utc) == target:
            return s
    return None


def price_levels(totals: list[float]) -> dict[str, float]:
    """Gränser för 'billig' (nedre tredjedel) och 'dyr' (övre tredjedel)."""
    if not totals:
        return {"low": 0.0, "high": 0.0}
    s = sorted(totals)
    return {
        "low": s[len(s) // 3],
        "high": s[min(len(s) - 1, (2 * len(s)) // 3)],
    }


def level_of(price: float, levels: dict[str, float]) -> str:
    if price <= levels["low"]:
        return "billig"
    if price >= levels["high"]:
        return "dyr"
    return "normal"


def as_attribute_list(
    slots: list[PriceSlot], tariff: TariffConfig
) -> list[dict[str, Any]]:
    """Serialiserbar lista som används av kortet (UI)."""
    return [
        {
            "start": s.start.isoformat(),
            "spot": round(s.spot, 4),
            "total": round(tariff.total_price(s.spot), 4),
        }
        for s in slots
    ]


def api_url(day: datetime, area: str) -> str:
    return (
        "https://www.elprisetjustnu.se/api/v1/prices/"
        f"{day:%Y}/{day:%m-%d}_{area}.json"
    )


def hours_ahead(start: datetime, n: int) -> list[datetime]:
    base = floor_hour(start)
    return [base + timedelta(hours=i) for i in range(n)]
