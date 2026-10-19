"""Konfigurationsflöde (på svenska via translations/sv.json)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector as sel

from .const import (
    AREAS,
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
    WFRAC_PLATFORMS,
)
from .core.tariff import TariffConfig


def _discover_wfrac(hass) -> dict[str, str]:
    """Hitta WF-RAC-entiteter i entitetsregistret (båda kända integrationerna)."""
    reg = er.async_get(hass)
    found: dict[str, str] = {}
    for e in reg.entities.values():
        if e.platform not in WFRAC_PLATFORMS or e.disabled:
            continue
        uid = (e.unique_id or "").lower()
        tk = (e.translation_key or "").lower()
        if e.domain == "climate" and CONF_CLIMATE not in found:
            found[CONF_CLIMATE] = e.entity_id
        elif e.domain == "sensor":
            if tk == "indoor" or "inside_temperature" in uid:
                found.setdefault(CONF_INDOOR_TEMP, e.entity_id)
            elif tk == "outdoor" or "outside_temperature" in uid:
                found.setdefault(CONF_OUTDOOR_TEMP, e.entity_id)
            elif tk == "energy_usage_total":
                found[CONF_HP_ENERGY] = e.entity_id  # föredra livstidstotalen
            elif tk == "energy_usage" or "energy" in uid:
                found.setdefault(CONF_HP_ENERGY, e.entity_id)
    return found


def _ent(domain: str | list[str], device_class: str | None = None, multiple: bool = False):
    cfg: dict[str, Any] = {"domain": domain, "multiple": multiple}
    if device_class:
        cfg["device_class"] = device_class
    return sel.EntitySelector(sel.EntitySelectorConfig(**cfg))


def _opt(key: str, d: dict[str, Any]):
    """Valfri entitet: förifyll bara om det finns ett värde."""
    return vol.Optional(key, description={"suggested_value": d.get(key)})


def _device_schema(hass, d: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_AREA, default=d.get(CONF_AREA, DEFAULT_AREA)): sel.SelectSelector(
                sel.SelectSelectorConfig(options=AREAS, mode=sel.SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(CONF_CLIMATE, description={"suggested_value": d.get(CONF_CLIMATE)}): _ent("climate"),
            _opt(CONF_INDOOR_TEMP, d): _ent("sensor", "temperature"),
            _opt(CONF_OUTDOOR_TEMP, d): _ent("sensor", "temperature"),
            _opt(CONF_HP_ENERGY, d): _ent("sensor", "energy"),
            vol.Required(CONF_HP_MAX_KW, default=d.get(CONF_HP_MAX_KW, 2.5)): sel.NumberSelector(
                sel.NumberSelectorConfig(min=0.5, max=15, step=0.1, unit_of_measurement="kW", mode="box")
            ),
            _opt(CONF_WEATHER, d): _ent("weather"),
            _opt(CONF_GRID_METER, d): _ent("sensor"),
            vol.Required(CONF_GRID_INVERT, default=d.get(CONF_GRID_INVERT, False)): sel.BooleanSelector(),
            _opt(CONF_SOLAR_POWER, d): _ent("sensor", "power"),
            _opt(CONF_BATTERY_POWER, d): _ent("sensor", "power"),
            vol.Required(CONF_BATTERY_INVERT, default=d.get(CONF_BATTERY_INVERT, False)): sel.BooleanSelector(),
            _opt(CONF_BATTERY_SOC, d): _ent("sensor", "battery"),
            _opt(CONF_EV_POWER, d): _ent("sensor", "power"),
            _opt(CONF_BOILER_SWITCH, d): _ent(["switch", "input_boolean"]),
            _opt(CONF_BOILER_ENERGY, d): _ent("sensor", "energy"),
            _opt(CONF_BOILER_TEMP, d): _ent("sensor", "temperature"),
            vol.Required(CONF_BOILER_HOURS, default=d.get(CONF_BOILER_HOURS, 3)): sel.NumberSelector(
                sel.NumberSelectorConfig(min=1, max=12, step=1, unit_of_measurement="h/dygn", mode="box")
            ),
            vol.Required(CONF_BOILER_MIN_TEMP, default=d.get(CONF_BOILER_MIN_TEMP, 45)): sel.NumberSelector(
                sel.NumberSelectorConfig(min=20, max=80, step=1, unit_of_measurement="°C", mode="box")
            ),
            vol.Required(CONF_BOILER_MAX_TEMP, default=d.get(CONF_BOILER_MAX_TEMP, 75)): sel.NumberSelector(
                sel.NumberSelectorConfig(min=30, max=90, step=1, unit_of_measurement="°C", mode="box")
            ),
            vol.Required(CONF_EV_KW, default=d.get(CONF_EV_KW, 7.4)): sel.NumberSelector(
                sel.NumberSelectorConfig(min=1, max=22, step=0.1, unit_of_measurement="kW", mode="box")
            ),
            vol.Required(CONF_SHOWER_DELAY, default=d.get(CONF_SHOWER_DELAY, 1)): sel.NumberSelector(
                sel.NumberSelectorConfig(min=0, max=6, step=1, unit_of_measurement="h", mode="box")
            ),
            vol.Optional(
                CONF_EXTRA_CONSUMERS, description={"suggested_value": d.get(CONF_EXTRA_CONSUMERS, [])}
            ): _ent("sensor", "energy", multiple=True),
        }
    )


def _num(key, default, unit, d, step=0.1, lo=0, hi=1000):
    return {
        vol.Required(key, default=d.get(key, default)): sel.NumberSelector(
            sel.NumberSelectorConfig(min=lo, max=hi, step=step, unit_of_measurement=unit, mode="box")
        )
    }


def _tariff_schema(d: dict[str, Any]) -> vol.Schema:
    t = TariffConfig()
    fields: dict = {}
    fields.update(_num(CONF_MARKUP, t.supplier_markup_ore, "öre/kWh", d))
    fields.update(_num(CONF_TRANSFER, t.grid_transfer_ore, "öre/kWh", d))
    fields.update(_num(CONF_TAX, t.energy_tax_ore, "öre/kWh", d))
    fields.update(_num(CONF_EFFECT_PRICE, t.effect_price_kr_kw, "kr/kW/mån", d))
    fields.update(_num(CONF_FIXED_FEE, t.fixed_fee_kr_month, "kr/mån", d))
    fields.update(_num(CONF_VAT, t.vat, "", d, step=0.01, hi=1))
    return vol.Schema(fields)


class SmartGridFlowConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_tariff()
        defaults = _discover_wfrac(self.hass)
        return self.async_show_form(step_id="user", data_schema=_device_schema(self.hass, defaults))

    async def async_step_tariff(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._data.update(user_input)
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Smart Grid Flow", data=self._data)
        return self.async_show_form(step_id="tariff", data_schema=_tariff_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return SmartGridFlowOptionsFlow()


class SmartGridFlowOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @property
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_tariff()
        return self.async_show_form(step_id="init", data_schema=_device_schema(self.hass, self._current))

    async def async_step_tariff(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="", data=self._data)
        return self.async_show_form(step_id="tariff", data_schema=_tariff_schema(self._current))
