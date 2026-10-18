"""Konstanter för Smart Grid Flow."""
from __future__ import annotations

DOMAIN = "smart_grid_flow"
PLATFORMS = ["sensor", "switch", "select", "number"]

CARD_URL = "/smart_grid_flow/smart-grid-flow-card.js"

# Konfiguration – enheter
CONF_AREA = "area"
CONF_CLIMATE = "climate_entity"
CONF_INDOOR_TEMP = "indoor_temp_entity"
CONF_OUTDOOR_TEMP = "outdoor_temp_entity"
CONF_HP_ENERGY = "heatpump_energy_entity"
CONF_HP_MAX_KW = "heatpump_max_kw"
CONF_WEATHER = "weather_entity"
CONF_GRID_METER = "grid_meter_entity"
CONF_BOILER_SWITCH = "boiler_switch_entity"
CONF_BOILER_ENERGY = "boiler_energy_entity"
CONF_BOILER_TEMP = "boiler_temp_entity"
CONF_BOILER_HOURS = "boiler_hours"
CONF_BOILER_MIN_TEMP = "boiler_min_temp"
CONF_BOILER_MAX_TEMP = "boiler_max_temp"
CONF_EV_KW = "ev_charger_kw"
CONF_SHOWER_DELAY = "shower_reheat_delay_h"
CONF_EXTRA_CONSUMERS = "extra_consumers"  # lista av energisensorer (kWh)

# Konfiguration – avgifter (standard: Göteborg Energi)
CONF_MARKUP = "supplier_markup_ore"
CONF_TRANSFER = "grid_transfer_ore"
CONF_TAX = "energy_tax_ore"
CONF_EFFECT_PRICE = "effect_price_kr_kw"
CONF_FIXED_FEE = "fixed_fee_kr_month"
CONF_VAT = "vat"

AREAS = ["SE1", "SE2", "SE3", "SE4"]
DEFAULT_AREA = "SE3"

# Integrationer som vi kan autodetektera värmepumpsentiteter från.
WFRAC_PLATFORMS = ("mitsubishi_wf_rac", "wf_rac")

UPDATE_INTERVAL_SECONDS = 60
OPTIMIZE_INTERVAL_SECONDS = 300
HORIZON_HOURS = 36
STORE_VERSION = 1

MODE_LABELS_SV = {
    "price": "Lägsta pris",
    "balanced": "Balanserad",
    "stable": "Stabil temperatur",
}
