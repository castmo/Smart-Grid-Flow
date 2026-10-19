"""Lämplighet per timme för stora, flyttbara förbrukare (elbilsladdning, dusch).

Poäng 0–100 där 100 = billigaste timmen i fönstret.

* Elbil: effektiv kostnad per kWh = elpris + tillägg om laddningen skulle skapa en ny
  effekttopp (effektavgift ⅓ per kW över tröskeln, eftersom topp-3 medelvärdesbildas).
* Dusch: energin förbrukas inte när man duschar utan när varmvattenberedaren värmer upp
  efteråt. Duschar man timme *h* betalar man alltså priset vid uppvärmningstimmen:
    - styr vi beredaren: första schemalagda timmen efter duschen (inom tankens buffert),
    - annars: ``h + fördröjning`` (beredaren startar oftast inom ca 1 h).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .optimizer import Step


PEAK_PENALTY_CAP = 1.0  # kr/kWh


def scores(costs: list[float]) -> list[int]:
    if not costs:
        return []
    lo, hi = min(costs), max(costs)
    if hi - lo < 1e-9:
        return [100] * len(costs)
    return [round(100 * (hi - c) / (hi - lo)) for c in costs]


def ev_suitability(
    steps: list[Step],
    ev_kw: float,
    other_kw: dict[datetime, float],
    base_kw: float,
    peak_threshold_kw: float,
    effect_price_kr_kw: float,
) -> list[dict]:
    costs = []
    for s in steps:
        total = other_kw.get(s.start, 0.0) + base_kw + ev_kw
        over = max(total - peak_threshold_kw, 0.0) if effect_price_kr_kw > 0 else 0.0
        # Straffet begränsas så att prisskillnader fortfarande syns i diagrammet.
        extra = min(effect_price_kr_kw / 3.0 * over / max(ev_kw, 0.1), PEAK_PENALTY_CAP)
        costs.append(s.price + extra)
    return [
        {"start": s.start.isoformat(), "score": sc, "cost": round(c, 3), "price": round(s.price, 3)}
        for s, sc, c in zip(steps, scores(costs), costs)
    ]


def reheat_index(
    i: int,
    steps: list[Step],
    schedule: set[datetime] | None,
    delay_h: int,
    buffer_h: int,
) -> int:
    n = len(steps)
    if schedule:
        for j in range(i, min(i + buffer_h + 1, n)):
            if steps[j].start in schedule:
                return j
    return min(i + max(delay_h, 0), n - 1)


def shower_suitability(
    steps: list[Step],
    schedule: set[datetime] | None,
    delay_h: int = 1,
    buffer_h: int = 8,
) -> list[dict]:
    idx = [reheat_index(i, steps, schedule, delay_h, buffer_h) for i in range(len(steps))]
    costs = [steps[j].price for j in idx]
    return [
        {
            "start": s.start.isoformat(),
            "score": sc,
            "cost": round(c, 3),
            "reheat": steps[j].start.isoformat(),
        }
        for s, sc, c, j in zip(steps, scores(costs), costs, idx)
    ]


def best_window(items: list[dict], hours: int, not_before: datetime) -> dict | None:
    """Bästa sammanhängande fönster (högst medelpoäng) som börjar nu eller senare."""
    cand = [
        (i, it) for i, it in enumerate(items)
        if datetime.fromisoformat(it["start"]) + timedelta(hours=1) > not_before
    ]
    best = None
    for i, _ in cand:
        w = items[i : i + hours]
        if len(w) < hours:
            break
        avg = sum(x["score"] for x in w) / hours
        if best is None or avg > best[0]:
            best = (avg, w)
    if not best:
        return None
    return {
        "start": best[1][0]["start"],
        "end": (datetime.fromisoformat(best[1][-1]["start"]) + timedelta(hours=1)).isoformat(),
        "score": round(best[0]),
    }
