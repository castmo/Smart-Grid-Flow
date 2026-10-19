"""Samordnare: hämtar priser/prognos, lär modellen, optimerar och styr enheter."""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AREA,
    CONF_BOILER_ENERGY,
    CONF_BOILER_HOURS,
    CONF_BOILER_MAX_TEMP,
    CONF_BOILER_MIN_TEMP,
    CONF_BOILER_SWITCH,
    CONF_BOILER_TEMP,
    CONF_CLIMATE,
    CONF_EFFECT_PRICE,
    CONF_BATTERY_INVERT,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_EV_KW,
    CONF_EV_POWER,
    CONF_GRID_INVERT,
    CONF_SOLAR_POWER,
    CONF_EXTRA_CONSUMERS,
    CONF_SHOWER_DELAY,
    CONF_FIXED_FEE,
    CONF_GRID_METER,
    CONF_HP_ENERGY,
    CONF_HP_MAX_KW,
    CONF_INDOOR_TEMP,
    CONF_MARKUP,
    CONF_OUTDOOR_TEMP,
    CONF_TAX,
    CONF_TRANSFER,
    CONF_VAT,
    CONF_WEATHER,
    DEFAULT_AREA,
    DOMAIN,
    HORIZON_HOURS,
    OPTIMIZE_INTERVAL_SECONDS,
    STORE_VERSION,
    UPDATE_INTERVAL_SECONDS,
)
from .core.learning import HeatPumpModel, Sample
from .core.optimizer import Mode, Plan, Settings, Step, optimize, round_setpoint
from .core.peak import HourAccumulator, PeakTracker
from .core.prices import (
    PriceSlot,
    api_url,
    as_attribute_list,
    floor_hour,
    future_slots,
    level_of,
    merge_slots,
    parse_elprisetjustnu,
    price_levels,
    slot_at,
)
from .core.suitability import best_window, ev_suitability, shower_suitability
from .core.scheduler import BoilerSettings, boiler_decision
from .core.tariff import TariffConfig

_LOGGER = logging.getLogger(__name__)

DEFAULT_RUNTIME: dict[str, Any] = {
    "mode": Mode.BALANCED.value,
    "target": 21.0,
    "comfort_min": 19.5,
    "setpoint_min": 18.0,
    "setpoint_max": 25.0,
    "hp_control": False,  # av tills användaren aktiverar styrning
    "boiler_control": False,
}

HEAT_STATES = ("heat", "heat_cool", "auto")


class SmartGridFlowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Hjärtat i integrationen."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.entry = entry
        self.store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}_{entry.entry_id}")
        self.runtime: dict[str, Any] = dict(DEFAULT_RUNTIME)
        self.model = HeatPumpModel()
        self.peak = PeakTracker()
        self.prices: list[PriceSlot] = []
        self.forecast: list[tuple[datetime, float]] = []
        self.plan: Plan | None = None
        self.boiler_info: dict[str, Any] = {}
        self.consumers: dict[str, dict[str, Any]] = {}
        self._cons_hist: dict[str, deque] = {}
        self._agg: dict[str, Any] | None = None
        self._grid_acc = HourAccumulator()
        self._closed: dict[str, dict[str, float]] = {}
        self._base_hist: list[float] = []
        self._last_price_try: datetime | None = None
        self._last_forecast_try: datetime | None = None
        self._last_opt: datetime | None = None
        self._force_opt = True
        self._last_sp_change: datetime | None = None
        self._last_hot: datetime | None = None
        self._boiler_last: bool | None = None

    # ------------------------------------------------------------------ config
    @property
    def cfg(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def tariff(self) -> TariffConfig:
        c = self.cfg
        d = TariffConfig()
        return TariffConfig(
            vat=float(c.get(CONF_VAT, d.vat)),
            supplier_markup_ore=float(c.get(CONF_MARKUP, d.supplier_markup_ore)),
            grid_transfer_ore=float(c.get(CONF_TRANSFER, d.grid_transfer_ore)),
            energy_tax_ore=float(c.get(CONF_TAX, d.energy_tax_ore)),
            effect_price_kr_kw=float(c.get(CONF_EFFECT_PRICE, d.effect_price_kr_kw)),
            fixed_fee_kr_month=float(c.get(CONF_FIXED_FEE, d.fixed_fee_kr_month)),
        )

    # ----------------------------------------------------------------- storage
    async def async_initialize(self) -> None:
        data = await self.store.async_load() or {}
        self.runtime.update(data.get("runtime", {}))
        self.model.load(data.get("model", {}))
        self.model.energy.max_kwh = float(self.cfg.get(CONF_HP_MAX_KW, 2.5))
        self.peak.load(data.get("peak", {}))
        self.consumers = data.get("consumers", {})
        self._base_hist = data.get("base_hist", [])
        if data.get("last_hot"):
            self._last_hot = dt_util.parse_datetime(data["last_hot"])

    def _save_payload(self) -> dict[str, Any]:
        return {
            "runtime": self.runtime,
            "model": self.model.to_dict(),
            "peak": self.peak.to_dict(),
            "consumers": self.consumers,
            "base_hist": self._base_hist[-24:],
            "last_hot": self._last_hot.isoformat() if self._last_hot else None,
        }

    def schedule_save(self) -> None:
        self.store.async_delay_save(self._save_payload, 60)

    async def async_set_runtime(self, key: str, value: Any) -> None:
        self.runtime[key] = value
        self._force_opt = True
        self.schedule_save()
        await self.async_request_refresh()

    # ------------------------------------------------------------ state helpers
    def _state(self, entity_id: str | None):
        if not entity_id:
            return None
        st = self.hass.states.get(entity_id)
        if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return st

    def _num(self, entity_id: str | None) -> float | None:
        st = self._state(entity_id)
        if st is None:
            return None
        try:
            return float(st.state)
        except (TypeError, ValueError):
            return None

    def _energy_kwh(self, entity_id: str | None) -> float | None:
        st = self._state(entity_id)
        if st is None:
            return None
        try:
            v = float(st.state)
        except (TypeError, ValueError):
            return None
        unit = st.attributes.get("unit_of_measurement")
        if unit == "Wh":
            v /= 1000.0
        elif unit == "MWh":
            v *= 1000.0
        return v

    # ----------------------------------------------------------------- prices
    async def _refresh_prices(self, now: datetime) -> None:
        today0 = dt_util.start_of_local_day(now)
        tomorrow_known = any(
            s.start >= today0 + timedelta(days=1) for s in self.prices
        )
        today_known = any(today0 <= s.start < today0 + timedelta(days=1) for s in self.prices)
        due = self._last_price_try is None or (now - self._last_price_try) > timedelta(minutes=30)
        need = (not today_known) or (not tomorrow_known and now.hour >= 13)
        if not (need and due):
            return
        self._last_price_try = now
        area = self.cfg.get(CONF_AREA, DEFAULT_AREA)
        session = async_get_clientsession(self.hass)
        days = [today0, today0 + timedelta(days=1)]
        fresh: list[PriceSlot] = []
        for day in days:
            try:
                async with session.get(api_url(day, area), timeout=15) as resp:
                    if resp.status == 200:
                        fresh += parse_elprisetjustnu(await resp.json())
                    elif resp.status != 404:  # 404 = morgondagens priser ej publicerade
                        _LOGGER.warning("Elpris-API svarade %s för %s", resp.status, day.date())
            except Exception as err:  # noqa: BLE001 - nätverksfel ska aldrig stoppa styrningen
                _LOGGER.warning("Kunde inte hämta elpriser: %s", err)
        if fresh:
            self.prices = [
                s for s in merge_slots(self.prices, fresh) if s.start >= today0
            ]
            self._force_opt = True

    # --------------------------------------------------------------- forecast
    async def _refresh_forecast(self, now: datetime) -> None:
        entity = self.cfg.get(CONF_WEATHER)
        if not entity:
            return
        if self._last_forecast_try and (now - self._last_forecast_try) < timedelta(minutes=30):
            return
        self._last_forecast_try = now
        try:
            resp = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": entity, "type": "hourly"},
                blocking=True,
                return_response=True,
            )
            items = (resp or {}).get(entity, {}).get("forecast", [])
            fc = []
            for it in items:
                t = it.get("temperature")
                when = dt_util.parse_datetime(str(it.get("datetime")))
                if t is not None and when is not None:
                    fc.append((when, float(t)))
            if fc:
                self.forecast = fc
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kunde inte hämta väderprognos: %s", err)

    def _t_out_at(self, when: datetime, fallback: float) -> float:
        best = None
        for t, v in self.forecast:
            if t <= when + timedelta(minutes=30):
                best = v
            else:
                break
        return best if best is not None else fallback

    # ------------------------------------------------------------------- main
    async def _async_update_data(self) -> dict[str, Any]:
        now = dt_util.now()
        cfg = self.cfg
        tariff = self.tariff
        await self._refresh_prices(now)
        await self._refresh_forecast(now)

        climate = self._state(cfg.get(CONF_CLIMATE))
        t_in = self._num(cfg.get(CONF_INDOOR_TEMP))
        if t_in is None and climate is not None:
            t_in = climate.attributes.get("current_temperature")
        t_out = self._num(cfg.get(CONF_OUTDOOR_TEMP))
        if t_out is None:
            w = self._state(cfg.get(CONF_WEATHER))
            if w is not None:
                t_out = w.attributes.get("temperature")
        t_in = float(t_in) if t_in is not None else None
        t_out = float(t_out) if t_out is not None else None
        hvac = climate.state if climate is not None else None
        hp_set = climate.attributes.get("temperature") if climate is not None else None
        hp_counter = self._energy_kwh(cfg.get(CONF_HP_ENERGY))

        self._track_hp_hour(now, t_in, t_out, hp_set if hvac in HEAT_STATES else None, hp_counter)
        self._track_grid(now)
        self._track_consumers(now, tariff)

        # Pris just nu
        cur_slot = slot_at(self.prices, now)
        today0 = dt_util.start_of_local_day(now)
        today_tot = [
            tariff.total_price(s.spot)
            for s in self.prices
            if today0 <= s.start < today0 + timedelta(days=1)
        ]
        all_tot = [tariff.total_price(s.spot) for s in future_slots(self.prices, now)]
        levels = price_levels(all_tot or today_tot)
        cur_total = tariff.total_price(cur_slot.spot) if cur_slot else None

        # Optimering
        await self._maybe_optimize(now, t_in, t_out, hvac, tariff)
        await self._apply_hp_control(now, hvac, climate)
        await self._apply_boiler(now, tariff)

        flow = self._flow()
        suit = self._suitability(now, tariff, t_out)
        fixed_hp_kw = self.consumers.get("heatpump", {}).get("power_kw", 0.0)
        data = {
            "now": now.isoformat(),
            "price": {
                "spot": cur_slot.spot if cur_slot else None,
                "total": cur_total,
                "level": level_of(cur_total, levels) if cur_total is not None else None,
                "levels": levels,
                "avg_today": mean(today_tot) if today_tot else None,
                "min_today": min(today_tot) if today_tot else None,
                "max_today": max(today_tot) if today_tot else None,
                "tomorrow_available": any(
                    s.start >= today0 + timedelta(days=1) for s in self.prices
                ),
            },
            "prices": as_attribute_list(self.prices, tariff),
            "hp": {
                "indoor": t_in,
                "outdoor": t_out,
                "setpoint": hp_set,
                "hvac_mode": hvac,
                "power_kw": fixed_hp_kw,
                "plan_setpoint": self.plan.setpoint_now if self.plan else None,
                "plan": self._plan_attr(),
                "plan_cost": self.plan.cost if self.plan else None,
                "plan_savings": self.plan.savings if self.plan else None,
                "control": self.runtime["hp_control"],
                "mode": self.runtime["mode"],
                "target": self.runtime["target"],
            },
            "boiler": self.boiler_info,
            "suitability": suit,
            "flow": flow,
            "consumers": list(self.consumers.values()),
            "peak": {
                "top": self.peak.top(),
                "billed_kw": self.peak.billed_kw(),
                "cost": self.peak.cost(tariff.effect_price_kr_kw),
                "threshold": self.peak.threshold(now),
                "price_kr_kw": tariff.effect_price_kr_kw,
                "month": self.peak.month,
            },
            "model": {
                "samples": min(self.model.thermal.samples, self.model.energy.samples),
                "confidence": self.model.confidence,
                "time_constant_h": self.model.thermal.time_constant_h,
                "thermal_error": self.model.thermal.abs_err,
                "energy_error": self.model.energy.abs_err,
                "heat_loss_per_h": self.model.thermal.rls.theta[0],
            },
        }
        return data

    def _power_kw(self, eid: str | None, invert: bool = False) -> float | None:
        st = self._state(eid)
        if st is None:
            return None
        try:
            v = float(st.state)
        except ValueError:
            return None
        unit = st.attributes.get("unit_of_measurement")
        if unit == "W":
            v /= 1000.0
        elif unit not in ("kW",):
            return None  # energimätare (kWh) duger inte som momentan effekt
        return -v if invert else v

    def _flow(self) -> dict[str, Any]:
        """Aktuella effektflöden (kW). Elnät: + = import. Batteri: + = laddning."""
        c = self.cfg
        grid = self._power_kw(c.get(CONF_GRID_METER), bool(c.get(CONF_GRID_INVERT)))
        solar = self._power_kw(c.get(CONF_SOLAR_POWER))
        batt = self._power_kw(c.get(CONF_BATTERY_POWER), bool(c.get(CONF_BATTERY_INVERT)))
        if batt is not None and not c.get(CONF_BATTERY_INVERT):
            pass  # + = laddning är standard
        soc = self._num(c.get(CONF_BATTERY_SOC))
        ev = self._power_kw(c.get(CONF_EV_POWER))
        hp = self.consumers.get("heatpump", {}).get("power_kw", 0.0)
        boiler = self.consumers.get("boiler", {}).get("power_kw", 0.0)
        solar_v = max(solar or 0.0, 0.0)
        batt_v = batt or 0.0
        known = hp + boiler + (ev or 0.0)
        if grid is not None:
            load = grid + solar_v - batt_v
        else:
            load = known
            grid = load + batt_v - solar_v
        other = max(load - known, 0.0)
        return {
            "grid": round(grid, 3),
            "solar": None if solar is None else round(solar_v, 3),
            "battery": None if batt is None else round(batt_v, 3),
            "soc": soc,
            "ev": None if ev is None else round(ev, 3),
            "heatpump": round(hp, 3),
            "boiler": round(boiler, 3),
            "other": round(other, 3),
            "load": round(load, 3),
            "grid_known": self._power_kw(c.get(CONF_GRID_METER)) is not None,
        }

    def _suitability(self, now: datetime, tariff: TariffConfig, t_out: float | None) -> dict[str, Any]:
        """Lämplighetsdiagram för elbilsladdning och dusch (hela dygnet inkl. imorgon)."""
        if len(self.prices) < 2:
            return {}
        c = self.cfg
        fb = t_out if t_out is not None else 5.0
        steps = [
            Step(s.start, tariff.total_price(s.spot), self._t_out_at(s.start, fb))
            for s in self.prices
        ]
        ev_kw = float(c.get(CONF_EV_KW, 7.4))
        delay = int(c.get(CONF_SHOWER_DELAY, 1))
        other = {p.start: p.energy_kwh for p in (self.plan.steps if self.plan else [])}
        opt = self._opt_settings(tariff)
        sched = None
        if self.runtime["boiler_control"] and self.boiler_info.get("schedule"):
            sched = {dt_util.parse_datetime(x) for x in self.boiler_info["schedule"]}
        ev = ev_suitability(
            steps, ev_kw, other, opt.base_load_kw, opt.peak_threshold_kw, opt.effect_price_kr_kw
        )
        shower = shower_suitability(steps, sched, delay)
        return {
            "ev": ev,
            "shower": shower,
            "ev_kw": ev_kw,
            "shower_delay_h": delay,
            "shower_scheduled": sched is not None,
            "best_ev_3h": best_window(ev, 3, now),
            "best_shower": best_window(shower, 1, now),
        }

    def _plan_attr(self) -> list[dict[str, Any]]:
        if not self.plan:
            return []
        return [
            {
                "start": p.start.isoformat(),
                "setpoint": p.setpoint,
                "t_in": round(p.t_in, 2),
                "t_out": round(p.t_out, 1),
                "kwh": round(p.energy_kwh, 3),
                "price": round(p.price, 3),
            }
            for p in self.plan.steps
        ]

    # --------------------------------------------------------------- learning
    def _track_hp_hour(
        self,
        now: datetime,
        t_in: float | None,
        t_out: float | None,
        setpoint: float | None,
        counter: float | None,
    ) -> None:
        h = floor_hour(now)
        a = self._agg
        if a is not None and a["start"] != h:
            self._close_hour(a, t_in, counter)
            a = None
        if a is None:
            a = {
                "start": h,
                "full": now.minute < 3,  # startade vi i början av timmen?
                "counter0": counter,
                "t_in": [],
                "t_out": [],
                "sp": [],
                "n": 0,
            }
            self._agg = a
        if a["counter0"] is None and counter is not None:
            a["counter0"] = counter
            a["full"] = False
        a["n"] += 1
        if t_in is not None:
            a["t_in"].append(t_in)
        if t_out is not None:
            a["t_out"].append(t_out)
        if setpoint is not None:
            a["sp"].append(float(setpoint))

    def _close_hour(self, a: dict[str, Any], t_in_end: float | None, counter: float | None) -> None:
        if not a["full"] or a["counter0"] is None or counter is None:
            return
        kwh = counter - a["counter0"]
        if kwh < 0 or kwh > 20 or not a["t_in"] or not a["t_out"] or t_in_end is None:
            return
        sp = mean(a["sp"]) if len(a["sp"]) >= 0.8 * a["n"] else None
        self.model.learn(Sample(a["t_in"][0], t_in_end, mean(a["t_out"]), sp, kwh))
        self._note_closed(a["start"], "hp", kwh)
        self.schedule_save()
        self._force_opt = True

    def _track_grid(self, now: datetime) -> None:
        eid = self.cfg.get(CONF_GRID_METER)
        st = self._state(eid)
        if st is None:
            return
        try:
            v = float(st.state)
        except ValueError:
            return
        unit = st.attributes.get("unit_of_measurement", "")
        if unit in ("W", "kW"):
            done = self._grid_acc.feed_power(now, v * (1000.0 if unit == "kW" else 1.0))
        else:
            kwh = v / 1000.0 if unit == "Wh" else v
            done = self._grid_acc.feed_counter(now, kwh)
        if done:
            hour, kwh = done
            self.peak.add_hour(hour, kwh)
            self._note_closed(hour, "grid", kwh)
            self.schedule_save()

    def _note_closed(self, hour: datetime, key: str, kwh: float) -> None:
        k = hour.isoformat()
        d = self._closed.setdefault(k, {})
        d[key] = kwh
        if "hp" in d and "grid" in d:
            self._base_hist.append(max(d["grid"] - d["hp"], 0.1))
            del self._base_hist[:-24]
            self._closed.pop(k, None)
        for old in sorted(self._closed)[:-4]:
            self._closed.pop(old, None)

    # --------------------------------------------------------------- consumers
    def _consumer_defs(self) -> list[tuple[str, str, str]]:
        c = self.cfg
        out = []
        if c.get(CONF_HP_ENERGY):
            out.append(("heatpump", "Värmepump", c[CONF_HP_ENERGY]))
        if c.get(CONF_BOILER_ENERGY):
            out.append(("boiler", "Varmvattenberedare", c[CONF_BOILER_ENERGY]))
        for i, eid in enumerate(c.get(CONF_EXTRA_CONSUMERS) or []):
            st = self.hass.states.get(eid)
            name = st.attributes.get("friendly_name", eid) if st else eid
            out.append((f"extra_{i}", name, eid))
        return out

    def _track_consumers(self, now: datetime, tariff: TariffConfig) -> None:
        day = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")
        cur_slot = slot_at(self.prices, now)
        price = tariff.total_price(cur_slot.spot) if cur_slot else 0.0
        for key, name, eid in self._consumer_defs():
            c = self.consumers.setdefault(
                key,
                {"key": key, "kwh_today": 0.0, "cost_today": 0.0, "kwh_month": 0.0,
                 "cost_month": 0.0, "last": None, "day": day, "month": month, "power_kw": 0.0},
            )
            c["name"], c["entity"] = name, eid
            if c.get("day") != day:
                c.update(day=day, kwh_today=0.0, cost_today=0.0)
            if c.get("month") != month:
                c.update(month=month, kwh_month=0.0, cost_month=0.0)
            v = self._energy_kwh(eid)
            if v is None:
                continue
            last = c.get("last")
            if last is not None and 0 <= v - last < 50:
                d = v - last
                c["kwh_today"] += d
                c["kwh_month"] += d
                c["cost_today"] += d * price
                c["cost_month"] += d * price
            c["last"] = v
            hist = self._cons_hist.setdefault(key, deque())
            hist.append((now, v))
            while hist and (now - hist[0][0]) > timedelta(minutes=20):
                hist.popleft()
            if len(hist) >= 2:
                dt_h = (hist[-1][0] - hist[0][0]).total_seconds() / 3600.0
                dv = hist[-1][1] - hist[0][1]
                c["power_kw"] = round(dv / dt_h, 3) if dt_h > 0 and dv >= 0 else 0.0

    # ------------------------------------------------------------- optimizer
    def _opt_settings(self, tariff: TariffConfig) -> Settings:
        r = self.runtime
        has_meter = bool(self.cfg.get(CONF_GRID_METER))
        base = mean(self._base_hist) if self._base_hist else 0.5
        thr = self.peak.threshold(dt_util.now())
        if thr <= 0:
            thr = 2.5
        return Settings(
            target=float(r["target"]),
            comfort_min=min(float(r["comfort_min"]), float(r["target"])),
            comfort_max=max(float(r["target"]) + 2.0, 23.0),
            setpoint_min=float(r["setpoint_min"]),
            setpoint_max=float(r["setpoint_max"]),
            mode=Mode(r["mode"]),
            effect_price_kr_kw=tariff.effect_price_kr_kw if has_meter else 0.0,
            peak_threshold_kw=thr,
            base_load_kw=base,
        )

    async def _maybe_optimize(
        self, now: datetime, t_in: float | None, t_out: float | None,
        hvac: str | None, tariff: TariffConfig,
    ) -> None:
        if t_in is None:
            return
        due = self._last_opt is None or (now - self._last_opt) > timedelta(seconds=OPTIMIZE_INTERVAL_SECONDS)
        if not (self._force_opt or due):
            return
        slots = future_slots(self.prices, now)[:HORIZON_HOURS]
        if len(slots) < 2:
            self.plan = None
            return
        fallback = t_out if t_out is not None else 5.0
        steps = [
            Step(s.start, tariff.total_price(s.spot), self._t_out_at(s.start, fallback))
            for s in slots
        ]
        cfg = self._opt_settings(tariff)
        try:
            self.plan = await self.hass.async_add_executor_job(
                optimize, t_in, steps, self.model.thermal, self.model.energy, cfg
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Optimeringen misslyckades")
            self.plan = None
        self._last_opt = now
        self._force_opt = False

    async def _apply_hp_control(self, now: datetime, hvac: str | None, climate) -> None:
        if not self.runtime["hp_control"] or self.plan is None or climate is None:
            return
        if hvac not in ("heat", "heat_cool", "auto"):
            return  # respektera att användaren stängt av / kör kyla
        cfg = self._opt_settings(self.tariff)
        want = round_setpoint(self.plan.setpoint_now, cfg)
        lo = climate.attributes.get("min_temp")
        hi = climate.attributes.get("max_temp")
        if lo is not None:
            want = max(want, float(lo))
        if hi is not None:
            want = min(want, float(hi))
        cur = climate.attributes.get("temperature")
        if cur is not None and abs(float(cur) - want) < 0.25:
            return
        # Minsta stilleståndstid så att enheten inte pendlar.
        if (
            self._last_sp_change
            and (now - self._last_sp_change) < timedelta(minutes=30)
            and cur is not None
            and abs(float(cur) - want) < 1.0
        ):
            return
        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": self.cfg[CONF_CLIMATE], "temperature": want},
            blocking=True,
        )
        self._last_sp_change = now
        _LOGGER.debug("Satte börvärde %.1f", want)

    async def _apply_boiler(self, now: datetime, tariff: TariffConfig) -> None:
        c = self.cfg
        sw = c.get(CONF_BOILER_SWITCH)
        if not sw:
            self.boiler_info = {}
            return
        slots = future_slots(self.prices, now)[:24]
        if len(slots) < 2:
            return
        fb = 5.0
        steps = [Step(s.start, tariff.total_price(s.spot), fb) for s in slots]
        temp = self._num(c.get(CONF_BOILER_TEMP))
        bs = BoilerSettings(
            run_hours_per_day=int(c.get(CONF_BOILER_HOURS, 3)),
            min_temp=float(c.get(CONF_BOILER_MIN_TEMP, 45)),
            max_temp=float(c.get(CONF_BOILER_MAX_TEMP, 75)),
        )
        if temp is not None and temp >= bs.legionella_temp:
            self._last_hot = now
        days = (now - self._last_hot).total_seconds() / 86400 if self._last_hot else None
        on, reason, chosen = boiler_decision(now, steps, bs, temp, days)
        sw_state = self._state(sw)
        is_on = sw_state is not None and sw_state.state == "on"
        if self.runtime["boiler_control"] and sw_state is not None and on != is_on:
            await self.hass.services.async_call(
                "homeassistant", "turn_on" if on else "turn_off",
                {"entity_id": sw}, blocking=True,
            )
        self.boiler_info = {
            "on": is_on,
            "wanted_on": on,
            "reason": reason,
            "temp": temp,
            "control": self.runtime["boiler_control"],
            "schedule": sorted(h.isoformat() for h in chosen),
        }
