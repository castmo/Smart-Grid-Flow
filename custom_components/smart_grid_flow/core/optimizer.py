"""Optimering av värmepumpens börvärde (dynamisk programmering).

Tillstånd: inomhustemperatur (rutnät 0,1 °C). Handling: börvärde per timme.
Kostnad per timme = elpris·kWh + komfortstraff + effektavgiftsstraff.
Slutvärde: värmelagring i huset värderas till medelpriset så att planen inte
"tömmer" huset i slutet av horisonten.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .learning import EnergyModel, ThermalModel


class Mode(StrEnum):
    PRICE = "price"  # Lägsta pris
    BALANCED = "balanced"  # Balanserad
    STABLE = "stable"  # Stabil temperatur
    AWAY = "away"  # Bortaläge (underhållsvärme ~12°C)


# (w_target, w_below, w_above) – SEK per °C² och timme.
MODE_WEIGHTS: dict[Mode, tuple[float, float, float]] = {
    Mode.PRICE: (0.04, 6.0, 1.0),
    Mode.BALANCED: (0.6, 12.0, 2.0),
    Mode.STABLE: (4.0, 30.0, 6.0),
    Mode.AWAY: (0.02, 12.0, 0.4),
}


@dataclass
class Settings:
    target: float = 21.0  # önskad innetemperatur
    comfort_min: float = 19.5  # får inte understigas om det går att undvika
    comfort_max: float = 23.0
    setpoint_min: float = 18.0
    setpoint_max: float = 25.0
    setpoint_step: float = 0.5
    mode: Mode = Mode.BALANCED
    effect_price_kr_kw: float = 0.0  # 0 = ingen effektstyrning
    peak_threshold_kw: float = 99.0  # nuvarande 3:e högsta timtopp
    base_load_kw: float = 0.5  # husets övriga last (för effektberäkning)
    t_grid_step: float = 0.1
    is_cooling: bool = False  # True om vi kör kyla (sommartid)


@dataclass
class Step:
    start: datetime
    price: float  # totalt SEK/kWh
    t_out: float


@dataclass
class PlanStep:
    start: datetime
    setpoint: float
    t_in: float  # prognos vid timmens start
    energy_kwh: float
    price: float
    cost: float
    t_out: float


@dataclass
class Plan:
    steps: list[PlanStep] = field(default_factory=list)
    cost: float = 0.0
    baseline_cost: float = 0.0
    baseline_t_end: float = 0.0

    @property
    def savings(self) -> float:
        return self.baseline_cost - self.cost

    @property
    def setpoint_now(self) -> float | None:
        return self.steps[0].setpoint if self.steps else None


def _frange(lo: float, hi: float, step: float) -> list[float]:
    n = int(round((hi - lo) / step))
    return [round(lo + i * step, 4) for i in range(n + 1)]


def simulate(
    t0: float,
    steps: list[Step],
    setpoints: list[float],
    thermal: ThermalModel,
    energy: EnergyModel,
) -> list[tuple[float, float]]:
    """Returnerar [(t_in_start, kWh)] för en given börvärdesföljd."""
    out = []
    t = t0
    for st, sp in zip(steps, setpoints):
        e = energy.predict(sp, t, st.t_out)
        out.append((t, e))
        t = t + thermal.predict_delta(t, st.t_out, e)
    out.append((t, 0.0))
    return out


def optimize(
    t_in: float,
    steps: list[Step],
    thermal: ThermalModel,
    energy: EnergyModel,
    cfg: Settings,
) -> Plan:
    n = len(steps)
    if n == 0:
        return Plan()
    w_t, w_lo, w_hi = MODE_WEIGHTS[cfg.mode]
    sps = _frange(cfg.setpoint_min, cfg.setpoint_max, cfg.setpoint_step)

    g = cfg.t_grid_step
    t_lo = min(cfg.comfort_min, t_in, cfg.target) - 4.0
    t_hi = max(cfg.comfort_max, t_in, cfg.target) + 2.0
    m = int(round((t_hi - t_lo) / g)) + 1

    def temp(i: int) -> float:
        return t_lo + i * g

    def comfort(t: float) -> float:
        c = w_t * (t - cfg.target) ** 2
        if t < cfg.comfort_min:
            c += w_lo * (cfg.comfort_min - t) ** 2
        elif t > cfg.comfort_max:
            c += w_hi * (t - cfg.comfort_max) ** 2
        return c

    mean_price = sum(s.price for s in steps) / n
    mid_out = sum(s.t_out for s in steps) / n
    gamma = max(thermal.rls.theta[1] + thermal.rls.theta[2] * mid_out / 10.0, 0.05)
    # Värde (SEK) av att sluta på temperatur T: kWh el som sparas/behövs.
    V = [mean_price * (cfg.target - temp(i)) / gamma for i in range(m)]
    # Begränsa lutningen så terminalvärdet aldrig dominerar priserna helt.
    policy: list[list[int]] = [[0] * m for _ in range(n)]
    e_cache: list[list[list[float]]] = []

    for k in range(n - 1, -1, -1):
        st = steps[k]
        # Förberäkna energi och nästa temperatur per (tillstånd, handling).
        newV = [0.0] * m
        e_row: list[list[float]] = []
        for i in range(m):
            t = temp(i)
            best = float("inf")
            best_a = 0
            e_i: list[float] = []
            base_c = comfort(t)
            for ai, sp in enumerate(sps):
                e = energy.predict(sp, t, st.t_out)
                e_i.append(e)
                t2 = t + thermal.predict_delta(t, st.t_out, e)
                f = (t2 - t_lo) / g
                if f <= 0:
                    v2 = V[0] + (f * (V[1] - V[0]) if m > 1 else 0.0)
                elif f >= m - 1:
                    v2 = V[m - 1] + (f - (m - 1)) * (V[m - 1] - V[m - 2])
                else:
                    i0 = int(f)
                    fr = f - i0
                    v2 = V[i0] * (1 - fr) + V[i0 + 1] * fr
                cost = st.price * e + base_c + v2
                if cfg.effect_price_kr_kw > 0:
                    over = e + cfg.base_load_kw - cfg.peak_threshold_kw
                    if over > 0:
                        cost += cfg.effect_price_kr_kw / 3.0 * over
                if cost < best:
                    best, best_a = cost, ai
            newV[i] = best
            policy[k][i] = best_a
            e_row.append(e_i)
        e_cache.append(e_row)
        V = newV

    # Framåtsimulering från verklig starttemperatur.
    plan = Plan()
    t = t_in
    for k, st in enumerate(steps):
        f = (t - t_lo) / g
        i = min(max(int(round(f)), 0), m - 1)
        sp = sps[policy[k][i]]
        e = energy.predict(sp, t, st.t_out)
        plan.steps.append(PlanStep(st.start, sp, t, e, st.price, st.price * e, st.t_out))
        t = t + thermal.predict_delta(t, st.t_out, e)
    plan.cost = sum(p.cost for p in plan.steps)

    # Referens: lägsta konstanta börvärde som ger minst lika hög medeltemperatur
    # och sluttemperatur som planen (rättvis jämförelse med samma komfort).
    plan_t = [p.t_in for p in plan.steps] + [t]
    plan_mean = sum(plan_t) / len(plan_t)
    base = None
    for sp in sps:
        sim = simulate(t_in, steps, [sp] * n, thermal, energy)
        temps = [x[0] for x in sim]
        base = sim
        if sum(temps) / len(temps) >= plan_mean - 0.05 and temps[-1] >= t - 0.3:
            break
    plan.baseline_cost = sum(st.price * e for st, (_, e) in zip(steps, base))
    plan.baseline_t_end = base[-1][0]
    return plan


def round_setpoint(value: float, cfg: Settings) -> float:
    step = cfg.setpoint_step
    v = round(value / step) * step
    return min(max(v, cfg.setpoint_min), cfg.setpoint_max)
