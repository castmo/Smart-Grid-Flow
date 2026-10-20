"""Inställningar som tal (önskad temperatur m.m.)."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import SGFBase

# (nyckel, min, max, steg)
NUMBERS = (
    ("target", 15.0, 26.0, 0.5),
    ("comfort_min", 12.0, 24.0, 0.5),
    ("setpoint_min", 10.0, 25.0, 0.5),
    ("setpoint_max", 18.0, 31.0, 0.5),
    ("away_target", 8.0, 18.0, 0.5),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SGFNumber(coord, entry, *n) for n in NUMBERS])


class SGFNumber(SGFBase, NumberEntity):
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = "°C"
    _attr_mode = NumberMode.BOX

    def __init__(self, coord, entry, key: str, lo: float, hi: float, step: float) -> None:
        super().__init__(coord, entry)
        self._key = key
        self._attr_translation_key = key
        self._attr_native_min_value = lo
        self._attr_native_max_value = hi
        self._attr_native_step = step
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    @property
    def native_value(self) -> float:
        val = self.coordinator.runtime.get(self._key)
        if val is None:
            val = self._attr_native_min_value
        return float(val)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_runtime(self._key, float(value))
