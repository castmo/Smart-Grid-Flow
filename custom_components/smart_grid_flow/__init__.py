"""Smart Grid Flow – smart elstyrning för Home Assistant."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CARD_URL, DOMAIN, PLATFORMS
from .coordinator import SmartGridFlowCoordinator

_LOGGER = logging.getLogger(__name__)


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registrera Lovelace-kortet så fort integrationen laddas (även före konfigurering)."""
    hass.data.setdefault(DOMAIN, {})
    card = Path(__file__).parent / "frontend" / "smart-grid-flow-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(card), False)]
    )
    manifest = Path(__file__).parent / "manifest.json"
    version = json.loads(await hass.async_add_executor_job(manifest.read_text))["version"]
    frontend.add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

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
