import random
from datetime import datetime, timedelta, timezone

from core.learning import HeatPumpModel, Sample, ThermalModel, EnergyModel
from core.optimizer import Mode, Settings, Step, optimize
from core.peak import HourAccumulator, PeakTracker
from core.prices import parse_elprisetjustnu, price_levels, level_of
from core.scheduler import BoilerSettings, boiler_decision, cheapest_hours
from core.tariff import TariffConfig

T0 = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)


def test_total_price():
    t = TariffConfig(supplier_markup_ore=0, grid_transfer_ore=23, energy_tax_ore=45)
    assert abs(t.total_price(1.0) - (1.25 + 0.68)) < 1e-9


def test_parse_quarter_hours():
    data = [
        {"SEK_per_kWh": v, "time_start": f"2026-11-03T00:{m:02d}:00+01:00"}
        for m, v in zip((0, 15, 30, 45), (1, 2, 3, 4))
    ]
    slots = parse_elprisetjustnu(data)
    assert len(slots) == 1 and slots[0].spot == 2.5


def test_levels():
    lv = price_levels([1, 2, 3, 4, 5, 6])
    assert level_of(1, lv) == "billig" and level_of(6, lv) == "dyr"


def steps(prices, t_out=0.0):
    return [Step(T0 + timedelta(hours=i), p, t_out) for i, p in enumerate(prices)]


def test_optimizer_shifts_load_to_cheap_hours():
    prices = [3.0] * 6 + [0.3] * 6 + [3.0] * 12
    cfg = Settings(mode=Mode.PRICE)
    plan = optimize(21.0, steps(prices), ThermalModel(), EnergyModel(), cfg)
    cheap = sum(p.energy_kwh for p in plan.steps[:12] if p.price < 1) 
    assert plan.savings > 0
    assert min(p.t_in for p in plan.steps) >= cfg.comfort_min - 1.0
    # Mer energi används under billiga timmar än dyra i snitt.
    e_cheap = sum(p.energy_kwh for p in plan.steps if p.price < 1) / 6
    e_dear = sum(p.energy_kwh for p in plan.steps if p.price > 1) / 18
    assert e_cheap > e_dear


def test_stable_mode_has_less_variation_than_price_mode():
    prices = [3.0] * 6 + [0.3] * 6 + [3.0] * 12
    def spread(mode):
        p = optimize(21.0, steps(prices), ThermalModel(), EnergyModel(), Settings(mode=mode))
        t = [s.t_in for s in p.steps]
        return max(t) - min(t)
    assert spread(Mode.STABLE) <= spread(Mode.PRICE)


def test_peak_penalty_reduces_peak():
    prices = [1.0] * 24
    base = optimize(18.0, steps(prices, -10), ThermalModel(), EnergyModel(), Settings(mode=Mode.BALANCED))
    cfg = Settings(mode=Mode.BALANCED, effect_price_kr_kw=49, peak_threshold_kw=1.0, base_load_kw=0.3)
    capped = optimize(18.0, steps(prices, -10), ThermalModel(), EnergyModel(), cfg)
    assert max(p.energy_kwh for p in capped.steps) <= max(p.energy_kwh for p in base.steps) + 1e-9


def test_learning_recovers_parameters():
    random.seed(1)
    true_a, g0, g1 = 0.05, 0.5, 0.02
    m = HeatPumpModel()
    t = 20.0
    for h in range(24 * 14):
        t_out = 2 + 6 * __import__("math").sin(h / 24 * 6.28) + random.gauss(0, 0.2)
        sp = 20 + 3 * __import__("math").sin(h / 5)
        e = max(0.0, 0.1 + 0.6 * max(sp - t, 0) + 0.2 * (t - t_out) / 10)
        t2 = t + true_a * (t_out - t) + (g0 + g1 * t_out / 10) * e + random.gauss(0, 0.01)
        m.learn(Sample(t, t2, t_out, sp, e))
        t = t2
    assert abs(m.thermal.rls.theta[0] - true_a) < 0.01
    assert m.thermal.abs_err < 0.05
    assert m.confidence == 1.0
    m2 = HeatPumpModel(); m2.load(m.to_dict())
    assert m2.thermal.rls.theta == m.thermal.rls.theta


def test_peak_tracker_top3_distinct_days():
    pt = PeakTracker()
    for d, kw in [(1, 3.0), (1, 5.0), (2, 4.0), (3, 2.0), (4, 1.0)]:
        pt.add_hour(datetime(2026, 11, d, 8), kw)
    assert pt.top() == [5.0, 4.0, 2.0]
    assert pt.threshold(datetime(2026, 11, 5)) == 2.0
    assert abs(pt.cost(49) - 49 * 11 / 3) < 1e-6
    pt.add_hour(datetime(2026, 12, 1, 8), 1.0)
    assert pt.top() == [1.0]


def test_hour_accumulator_counter_and_power():
    a = HourAccumulator()
    assert a.feed_counter(datetime(2026, 1, 1, 10, 0), 100.0) is None
    assert a.feed_counter(datetime(2026, 1, 1, 10, 30), 100.7) is None
    done = a.feed_counter(datetime(2026, 1, 1, 11, 0, 5), 101.5)
    assert done and abs(done[1] - 0.7) < 1e-9
    p = HourAccumulator()
    for m in range(0, 61, 5):
        done = p.feed_power(datetime(2026, 1, 1, 10 + m // 60, m % 60), 2000.0)
    assert done and abs(done[1] - 2.0 * 55 / 60) < 0.2


def test_boiler():
    st = steps([5, 4, 1, 1, 1, 6, 7, 8] + [5] * 16)
    assert cheapest_hours(st, 3) == {st[2].start, st[3].start, st[4].start}
    on, why, _ = boiler_decision(st[2].start, st, BoilerSettings(), temp=60)
    assert on and why == "schema"
    on, why, _ = boiler_decision(st[0].start, st, BoilerSettings(), temp=40)
    assert on and why == "min_temp"
    on, _, _ = boiler_decision(st[2].start, st, BoilerSettings(), temp=80)
    assert not on


def test_suitability_ev_and_shower():
    from core.suitability import best_window, ev_suitability, shower_suitability
    st = steps([5, 4, 1, 1, 6, 7, 2, 2])
    ev = ev_suitability(st, 7.4, {}, 0.5, 99, 0)
    assert ev[2]["score"] == 100 and ev[5]["score"] == 0
    # Dusch utan styrning: kostnad = pris vid h+1 -> timmen före en billig timme är bäst.
    sh = shower_suitability(st, None, delay_h=1)
    assert sh[1]["score"] == 100 and sh[1]["reheat"] == st[2].start.isoformat()
    # Med schema: duschar man timme 4 värms vattnet först vid nästa schemalagda timme.
    sh2 = shower_suitability(st, {st[6].start}, delay_h=1)
    assert sh2[4]["reheat"] == st[6].start.isoformat()
    w = best_window(ev, 2, T0)
    assert w["start"] == st[2].start.isoformat()


def test_ev_peak_penalty():
    from core.suitability import ev_suitability
    st = steps([1.0, 1.0])
    ev = ev_suitability(st, 7.4, {st[0].start: 3.0}, 0.5, 5.0, 49)
    assert ev[0]["cost"] >= ev[1]["cost"] > 1.0  # straff över tröskeln, begränsad till 1 kr/kWh
    assert ev[1]["cost"] <= 2.0 + 1e-9
