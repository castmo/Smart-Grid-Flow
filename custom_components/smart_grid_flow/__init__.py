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

# Tillåt både UI-konfigurering och eventuell rad i configuration.yaml
CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


async def _async_register_lovelace_card(hass: HomeAssistant) -> None:
    """Registrerar Lovelace-kortet på alla sätt som Home Assistant stöder."""
    card_dir = Path(__file__).parent / "frontend"
    card_file = card_dir / "smart-grid-flow-card.js"
    manifest_file = Path(__file__).parent / "manifest.json"

    # 1. Statisk sökväg: /smart_grid_flow/smart-grid-flow-card.js
    if not hass.data.get(f"{DOMAIN}_static_registered"):
        try:
            await hass.http.async_register_static_paths(
                [StaticPathConfig(CARD_URL, str(card_file), False)]
            )
            hass.data[f"{DOMAIN}_static_registered"] = True
        except Exception as err:
            _LOGGER.debug("Statisk sökväg redan registrerad eller fel: %s", err)

    # 2. Version från manifest för cache-busting
    try:
        manifest = json.loads(await hass.async_add_executor_job(manifest_file.read_text))
        version = manifest.get("version", "0.1.2")
    except Exception:
        version = "0.1.2"
    url_with_version = f"{CARD_URL}?v={version}"

    # 3. Lägg till i Home Assistants frontend-moduler
    frontend.add_extra_js_url(hass, url_with_version)

    # 4. Lägg automatiskt till/uppdatera i Dashboard Resources (om Lovelace körs i lagringsläge)
    if "lovelace" in hass.data:
        ll = hass.data["lovelace"]
        res = getattr(ll, "resources", None)
        if res and hasattr(res, "async_items"):
            try:
                if not getattr(res, "loaded", True):
                    await res.async_load()
                items = list(res.async_items())
                found = False
                for item in items:
                    u = item.get("url", "")
                    base_u = u.split("?")[0]
                    if base_u in (CARD_URL, "/local/smart_grid_flow/smart-grid-flow-card.js"):
                        found = True
                        if u != url_with_version and hasattr(res, "async_update_item"):
                            await res.async_update_item(
                                item["id"], {"res_type": "module", "url": url_with_version}
                            )
                            _LOGGER.info(
                                "Smart Grid Flow: Uppdaterade Lovelace-resurs till %s",
                                url_with_version,
                            )
                if not found and hasattr(res, "async_create_item"):
                    await res.async_create_item({"res_type": "module", "url": url_with_version})
                    _LOGGER.info("Smart Grid Flow: Registrerade Lovelace-resurs %s", url_with_version)
            except Exception as err:
                _LOGGER.debug("Kunde inte auto-registrera Lovelace-resurs: %s", err)

    # 5. Kopiera till www/smart_grid_flow/ så /local/smart_grid_flow/ alltid fungerar som reserv
    def _copy_to_www():
        try:
            www_dir = Path(hass.config.path("www", "smart_grid_flow"))
            www_dir.mkdir(parents=True, exist_ok=True)
            dest = www_dir / "smart-grid-flow-card.js"
            if not dest.exists() or dest.read_bytes() != card_file.read_bytes():
                dest.write_bytes(card_file.read_bytes())
                _LOGGER.debug("Kopierade kort till %s", dest)
        except Exception as err:
            _LOGGER.debug("Kunde inte kopiera till www: %s", err)

    await hass.async_add_executor_job(_copy_to_www)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Initiering vid uppstart av Home Assistant."""
    hass.data.setdefault(DOMAIN, {})
    await _async_register_lovelace_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initiering av en konfigurationsinstans."""
    hass.data.setdefault(DOMAIN, {})
    await _async_register_lovelace_card(hass)

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
