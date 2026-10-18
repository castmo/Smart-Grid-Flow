"""Smart Grid Flow – smart elstyrning för Home Assistant."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CARD_URL, DOMAIN, PLATFORMS
from .coordinator import SmartGridFlowCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    # Registrera Lovelace-kortet automatiskt (inga manuella resurser behövs).
    if not hass.data[DOMAIN].get("_card_registered"):
        card = Path(__file__).parent / "frontend" / "smart-grid-flow-card.js"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(card), False)]
        )
        frontend.add_extra_js_url(hass, CARD_URL)
        hass.data[DOMAIN]["_card_registered"] = True

    coordinator = SmartGridFlowCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload_on_options))
    return True


async def _reload_on_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: SmartGridFlowCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.store.async_save(coordinator._save_payload())
    return unloaded
