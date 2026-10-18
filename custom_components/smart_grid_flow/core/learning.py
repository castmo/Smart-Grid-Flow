"""Självlärande modeller (rekursiv minstakvadrat med glömskefaktor).

Två små modeller lär sig av historiken, en gång per fullbordad timme:

* ``ThermalModel``  – hur inomhustemperaturen ändras:
      ΔT = a·(T_ute − T_inne) + (g0 + g1·T_ute/10)·E + b
  där E är värmepumpens elförbrukning (kWh) under timmen. g1 fångar att
  värmefaktorn (COP) stiger med utetemperaturen.

* ``EnergyModel``   – hur mycket el värmepumpen drar för en given börtemperatur:
      E = e0 + e1·max(börvärde − T_inne, 0) + e2·(T_inne − T_ute)/10
  Detta är den "förbrukning givet börvärde" som WF-RAC-energisensorn gör
  möjlig att lära in.

Allt är ren Python så att det kan testas utan Home Assistant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


class RLS:
    """Rekursiv minstakvadrat med forgetting factor och parametergränser."""

    def __init__(
        self,
        theta: Sequence[float],
        p0: float = 10.0,
        forgetting: float = 0.998,
        bounds: Sequence[tuple[float, float]] | None = None,
    ) -> None:
        n = len(theta)
        self.theta = list(theta)
        self.P = [[p0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        self.lam = forgetting
        self.bounds = list(bounds) if bounds else None

    def predict(self, x: Sequence[float]) -> float:
        return sum(t * xi for t, xi in zip(self.theta, x))

    def update(self, x: Sequence[float], y: float) -> float:
        n = len(self.theta)
        px = [sum(self.P[i][j] * x[j] for j in range(n)) for i in range(n)]
        denom = self.lam + sum(x[i] * px[i] for i in range(n))
        k = [v / denom for v in px]
        err = y - self.predict(x)
        self.theta = [self.theta[i] + k[i] * err for i in range(n)]
        xtp = [sum(x[i] * self.P[i][j] for i in range(n)) for j in range(n)]
        self.P = [
            [(self.P[i][j] - k[i] * xtp[j]) / self.lam for j in range(n)]
            for i in range(n)
        ]
        # Hindra att P växer okontrollerat när insignalen saknar variation.
        for i in range(n):
            self.P[i][i] = min(self.P[i][i], 1e3)
        if self.bounds:
            self.theta = [
                min(max(t, lo), hi) for t, (lo, hi) in zip(self.theta, self.bounds)
            ]
        return err

    def to_dict(self) -> dict[str, Any]:
        return {"theta": self.theta, "P": self.P}

    def load(self, data: dict[str, Any]) -> None:
        if len(data.get("theta", [])) == len(self.theta):
            self.theta = [float(v) for v in data["theta"]]
            self.P = [[float(v) for v in row] for row in data["P"]]


@dataclass
class Sample:
    """En timmes mätdata."""

    t_in: float  # inomhus, början av timmen (°C)
    t_in_next: float  # inomhus, slutet av timmen (°C)
    t_out: float  # medel utomhus (°C)
    setpoint: float | None  # medel börvärde (None = av)
    energy_kwh: float  # värmepumpens el under timmen


class ThermalModel:
    # [a, g0, g1, b]
    PRIOR = [0.03, 0.30, 0.03, 0.0]
    BOUNDS = [(0.003, 0.25), (0.02, 3.0), (-0.05, 0.4), (-0.3, 0.3)]

    def __init__(self) -> None:
        self.rls = RLS(self.PRIOR, p0=0.5, bounds=self.BOUNDS)
        self.samples = 0
        self.abs_err = 0.0  # glidande medelfel (°C/h)

    @staticmethod
    def features(t_in: float, t_out: float, energy: float) -> list[float]:
        return [t_out - t_in, energy, energy * t_out / 10.0, 1.0]

    def predict_delta(self, t_in: float, t_out: float, energy: float) -> float:
        return self.rls.predict(self.features(t_in, t_out, energy))

    def update(self, s: Sample) -> None:
        x = self.features(s.t_in, s.t_out, s.energy_kwh)
        err = self.rls.update(x, s.t_in_next - s.t_in)
        self.samples += 1
        self.abs_err = 0.95 * self.abs_err + 0.05 * abs(err) if self.samples > 1 else abs(err)

    @property
    def time_constant_h(self) -> float:
        return 1.0 / max(self.rls.theta[0], 1e-6)

    def to_dict(self) -> dict[str, Any]:
        return {"rls": self.rls.to_dict(), "samples": self.samples, "err": self.abs_err}

    def load(self, d: dict[str, Any]) -> None:
        self.rls.load(d.get("rls", {}))
        self.samples = int(d.get("samples", 0))
        self.abs_err = float(d.get("err", 0.0))


class EnergyModel:
    # [e0, e1, e2]
    PRIOR = [0.0, 0.45, 0.30]
    BOUNDS = [(-0.5, 1.0), (0.02, 3.0), (0.0, 2.0)]

    def __init__(self, max_kwh_per_hour: float = 2.5) -> None:
        self.rls = RLS(self.PRIOR, p0=0.5, bounds=self.BOUNDS)
        self.max_kwh = max_kwh_per_hour
        self.samples = 0
        self.abs_err = 0.0

    @staticmethod
    def features(setpoint: float, t_in: float, t_out: float) -> list[float]:
        return [1.0, max(setpoint - t_in, 0.0), (t_in - t_out) / 10.0]

    def predict(self, setpoint: float, t_in: float, t_out: float) -> float:
        e = self.rls.predict(self.features(setpoint, t_in, t_out))
        return min(max(e, 0.0), self.max_kwh)

    def update(self, s: Sample) -> None:
        if s.setpoint is None:
            return
        # Ignorera timmar då maskinen tydligt var avstängd/otillgänglig.
        x = self.features(s.setpoint, s.t_in, s.t_out)
        err = self.rls.update(x, min(s.energy_kwh, self.max_kwh))
        self.samples += 1
        self.abs_err = 0.95 * self.abs_err + 0.05 * abs(err) if self.samples > 1 else abs(err)

    def to_dict(self) -> dict[str, Any]:
        return {"rls": self.rls.to_dict(), "samples": self.samples, "err": self.abs_err}

    def load(self, d: dict[str, Any]) -> None:
        self.rls.load(d.get("rls", {}))
        self.samples = int(d.get("samples", 0))
        self.abs_err = float(d.get("err", 0.0))


@dataclass
class HeatPumpModel:
    """Paketerar de två modellerna + ett rullande urval av råa timprov."""

    thermal: ThermalModel = field(default_factory=ThermalModel)
    energy: EnergyModel = field(default_factory=EnergyModel)
    history: list[dict[str, float | None]] = field(default_factory=list)
    max_history: int = 24 * 60

    def learn(self, s: Sample) -> None:
        # Orimliga hopp (t.ex. fönster öppnade/sensorfel) lär vi oss inte av.
        if abs(s.t_in_next - s.t_in) > 3.0:
            return
        self.thermal.update(s)
        self.energy.update(s)
        self.history.append(
            {
                "t_in": round(s.t_in, 2),
                "t_in_next": round(s.t_in_next, 2),
                "t_out": round(s.t_out, 2),
                "sp": None if s.setpoint is None else round(s.setpoint, 2),
                "kwh": round(s.energy_kwh, 3),
            }
        )
        del self.history[: -self.max_history]

    def to_dict(self) -> dict[str, Any]:
        return {
            "thermal": self.thermal.to_dict(),
            "energy": self.energy.to_dict(),
            "history": self.history,
        }

    def load(self, d: dict[str, Any]) -> None:
        self.thermal.load(d.get("thermal", {}))
        self.energy.load(d.get("energy", {}))
        self.history = list(d.get("history", []))

    @property
    def confidence(self) -> float:
        """0–1: hur mycket data modellen har (full vid ~7 dygn)."""
        return min(1.0, min(self.thermal.samples, self.energy.samples) / (7 * 24))
