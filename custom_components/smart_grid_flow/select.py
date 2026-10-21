"""Val av optimeringsläge."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODE_LABELS_SV
from .sensor import SGFBase

_BY_LABEL = {v: k for k, v in MODE_LABELS_SV.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([SGFModeSelect(hass.data[DOMAIN][entry.entry_id], entry)])


class SGFModeSelect(SGFBase, SelectEntity):
    _attr_translation_key = "mode"
    _attr_options = list(MODE_LABELS_SV.values())

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry)
        self._attr_unique_id = f"{entry.entry_id}_mode"

    @property
    def current_option(self) -> str:
        return MODE_LABELS_SV.get(self.coordinator.runtime.get("mode", "balanced"), MODE_LABELS_SV["balanced"])

    async def async_select_option(self, option: str) -> None:
        key = _BY_LABEL.get(option, "balanced")
        await self.coordinator.async_set_runtime("mode", key)
        if key == "away":
            await self.coordinator.async_set_runtime("away_mode", True)
        else:
            await self.coordinator.async_set_runtime("away_mode", False)
