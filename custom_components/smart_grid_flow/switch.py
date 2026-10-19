"""Strömbrytare för att aktivera/avaktivera styrning."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_BOILER_SWITCH, DOMAIN
from .sensor import SGFBase


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    ents = [
        SGFControlSwitch(coord, entry, "hp_control", "hp_control"),
        SGFAwaySwitch(coord, entry),
        SGFControlSwitch(coord, entry, "auto_season", "auto_season"),
    ]
    if coord.cfg.get(CONF_BOILER_SWITCH):
        ents.append(SGFControlSwitch(coord, entry, "boiler_control", "boiler_control"))
    async_add_entities(ents)


class SGFControlSwitch(SGFBase, SwitchEntity):
    def __init__(self, coord, entry, key: str, translation_key: str) -> None:
        super().__init__(coord, entry)
        self._key = key
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.runtime.get(self._key))

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_runtime(self._key, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_runtime(self._key, False)


class SGFAwaySwitch(SGFBase, SwitchEntity):
    """Strömbrytare för Bortaläge (underhållsvärme ~12°C, värmeläge)."""

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry)
        self._attr_translation_key = "away_mode"
        self._attr_unique_id = f"{entry.entry_id}_away_mode"
        self._attr_icon = "mdi:home-export-outline"

    @property
    def is_on(self) -> bool:
        return bool(
            self.coordinator.runtime.get("away_mode")
            or self.coordinator.runtime.get("mode") == "away"
        )

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_runtime("away_mode", True)
        await self.coordinator.async_set_runtime("mode", "away")

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_runtime("away_mode", False)
        if self.coordinator.runtime.get("mode") == "away":
            await self.coordinator.async_set_runtime("mode", "balanced")
