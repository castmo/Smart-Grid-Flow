"""Genererar exempeldata (med den riktiga kärnlogiken) och en demosida för kortet.

    python docs/demo/make_sample.py     ->  docs/demo/index.html

Öppna index.html i en webbläsare (eller ta skärmdump med Playwright) för att se kortet
med påhittad men realistisk data: moln-fritt, solig förmiddag, batteri och elbil.
"""
import json
import math
import pathlib
import sys
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "custom_components" / "smart_grid_flow"))

from core.learning import HeatPumpModel  # noqa: E402
from core.optimizer import Mode, Settings, Step, optimize  # noqa: E402
from core.peak import PeakTracker  # noqa: E402
from core.prices import PriceSlot, as_attribute_list, price_levels, level_of  # noqa: E402
from core.scheduler import BoilerSettings, boiler_decision  # noqa: E402
from core.suitability import best_window, ev_suitability, shower_suitability  # noqa: E402
from core.tariff import TariffConfig  # noqa: E402

now = datetime.now().astimezone()
today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
tariff = TariffConfig()


def spot(h: int) -> float:
    day = h % 24
    base = 0.55 + 0.35 * math.exp(-((day - 8) ** 2) / 6) + 0.6 * math.exp(-((day - 18.5) ** 2) / 5)
    base -= 0.25 * math.exp(-((day - 3) ** 2) / 10)
    return round(base * (1.25 if h >= 24 else 1.0), 3)


slots = [PriceSlot(today0 + timedelta(hours=h), spot(h)) for h in range(48)]
future = [s for s in slots if s.start + timedelta(hours=1) > now]
steps = [Step(s.start, tariff.total_price(s.spot), 2.0 - 0.1 * i / 6) for i, s in enumerate(future[:36])]
allsteps = [Step(s.start, tariff.total_price(s.spot), 2.0) for s in slots]

m = HeatPumpModel()
cfg = Settings(mode=Mode.BALANCED, effect_price_kr_kw=49, peak_threshold_kw=4.2, base_load_kw=0.6)
plan = optimize(21.0, steps, m.thermal, m.energy, cfg)

levels = price_levels([tariff.total_price(s.spot) for s in future])
cur = tariff.total_price(slots[now.hour].spot)
sched = None
bs = BoilerSettings()
_, _, chosen = boiler_decision(now, steps[:24], bs, 52.0)
sched = chosen
other = {p.start: p.energy_kwh for p in plan.steps}
ev = ev_suitability(allsteps, 11.0, other, 0.6, 4.2, 49)
shower = shower_suitability(allsteps, sched, 1)
today_tot = [tariff.total_price(s.spot) for s in slots[:24]]

pk = PeakTracker()
for d, kw in ((2, 4.8), (7, 4.2), (12, 3.9)):
    pk.add_hour(datetime(now.year, now.month, 1).replace(day=min(d, 28)), kw)

attrs = {
    "now": now.isoformat(),
    "price": {
        "spot": slots[now.hour].spot, "total": cur, "level": level_of(cur, levels), "levels": levels,
        "avg_today": sum(today_tot) / 24, "min_today": min(today_tot), "max_today": max(today_tot),
        "tomorrow_available": True,
    },
    "prices": as_attribute_list(slots, tariff),
    "hp": {
        "indoor": 20.8, "outdoor": 3.5, "setpoint": 21.5, "hvac_mode": "heat", "power_kw": 1.2,
        "plan_setpoint": plan.setpoint_now,
        "plan": [{"start": p.start.isoformat(), "setpoint": p.setpoint, "t_in": p.t_in,
                  "t_out": p.t_out, "kwh": p.energy_kwh, "price": p.price} for p in plan.steps],
        "plan_cost": plan.cost, "plan_savings": plan.savings, "control": True, "mode": "balanced", "target": 21.0,
    },
    "boiler": {"on": True, "wanted_on": True, "reason": "schema", "temp": 58.0, "control": True,
               "schedule": sorted(h.isoformat() for h in chosen)},
    "suitability": {
        "ev": ev, "shower": shower, "ev_kw": 11.0, "shower_delay_h": 1, "shower_scheduled": True,
        "best_ev_3h": best_window(ev, 3, now), "best_shower": best_window(shower, 1, now),
    },
    "flow": {
        "grid": 3.1, "solar": 2.4, "battery": 1.5, "soc": 62, "ev": 3.2, "heatpump": 1.2,
        "boiler": 1.9, "other": 0.5, "load": 7.0, "grid_known": True,
    },
    "consumers": [
        {"key": "heatpump", "name": "Värmepump", "kwh_today": 14.8, "cost_today": 17.2, "power_kw": 1.2},
        {"key": "boiler", "name": "Varmvattenberedare", "kwh_today": 4.6, "cost_today": 3.9, "power_kw": 1.9},
        {"key": "ev", "name": "Elbil", "kwh_today": 21.0, "cost_today": 16.5, "power_kw": 3.2},
    ],
    "peak": {"top": pk.top(), "billed_kw": pk.billed_kw(), "cost": pk.cost(49), "threshold": pk.threshold(now),
             "price_kr_kw": 49, "month": now.strftime("%Y-%m")},
    "model": {"samples": 132, "confidence": 0.79, "time_constant_h": 31.0, "thermal_error": 0.04,
              "energy_error": 0.09, "heat_loss_per_h": 0.032},
    "sgf_overview": True,
}

card = (ROOT / "custom_components/smart_grid_flow/frontend/smart-grid-flow-card.js").read_text()
html = f"""<!doctype html><meta charset="utf-8"><title>Smart Grid Flow – demo</title>
<style>
 :root{{--card-background-color:#fff;--primary-text-color:#212121;--secondary-text-color:#727272;
  --divider-color:#e0e0e0;--primary-color:#03a9f4;--secondary-background-color:#f1f3f4}}
 body{{margin:0;padding:24px;background:#eceff1;font-family:Roboto,Arial,sans-serif;display:flex;justify-content:center}}
 .wrap{{width:520px}}
 ha-card{{display:block;background:var(--card-background-color);border-radius:12px;color:var(--primary-text-color);
  box-shadow:0 2px 6px rgba(0,0,0,.15)}}
</style>
<div class="wrap" id="root"></div>
<script>{card}</script>
<script>
 const attrs = {json.dumps(attrs, ensure_ascii=False)};
 const card = document.createElement('smart-grid-flow-card');
 card.setConfig({{}});
 document.getElementById('root').appendChild(card);
 card.hass = {{ states: {{ 'sensor.smart_grid_flow_oversikt': {{ state: 'normal', last_updated: 'x', attributes: attrs }} }},
   entities: {{}}, callService(){{}} }};
</script>"""
(ROOT / "docs/demo").mkdir(parents=True, exist_ok=True)
(ROOT / "docs/demo/index.html").write_text(html)
print("skrev docs/demo/index.html")
