"""Sensorer."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SmartGridFlowCoordinator


def device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Smart Grid Flow",
        manufacturer="castmo",
        model="Elstyrning",
    )


@dataclass(frozen=True, kw_only=True)
class SGFSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]


def _plan_kwh(d: dict[str, Any]) -> float | None:
    plan = d["hp"]["plan"]
    return round(plan[0]["kwh"], 2) if plan else None


SENSORS: tuple[SGFSensorDescription, ...] = (
    SGFSensorDescription(
        key="price_total", translation_key="price_total", native_unit_of_measurement="kr/kWh",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2,
        value_fn=lambda d: d["price"]["total"],
    ),
    SGFSensorDescription(
        key="price_spot", translation_key="price_spot", native_unit_of_measurement="kr/kWh",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2,
        value_fn=lambda d: d["price"]["spot"],
    ),
    SGFSensorDescription(
        key="price_level", translation_key="price_level",
        device_class=SensorDeviceClass.ENUM, options=["billig", "normal", "dyr"],
        value_fn=lambda d: d["price"]["level"],
    ),
    SGFSensorDescription(
        key="price_avg_today", translation_key="price_avg_today", native_unit_of_measurement="kr/kWh",
        suggested_display_precision=2, value_fn=lambda d: d["price"]["avg_today"],
    ),
    SGFSensorDescription(
        key="hp_plan_setpoint", translation_key="hp_plan_setpoint",
        device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement="°C",
        value_fn=lambda d: d["hp"]["plan_setpoint"],
    ),
    SGFSensorDescription(
        key="hp_plan_energy", translation_key="hp_plan_energy",
        device_class=SensorDeviceClass.ENERGY, native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=_plan_kwh,
    ),
    SGFSensorDescription(
        key="hp_plan_savings", translation_key="hp_plan_savings", native_unit_of_measurement="kr",
        suggested_display_precision=2, value_fn=lambda d: d["hp"]["plan_savings"],
    ),
    SGFSensorDescription(
        key="peak_billed", translation_key="peak_billed",
        device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2, value_fn=lambda d: d["peak"]["billed_kw"],
    ),
    SGFSensorDescription(
        key="peak_cost", translation_key="peak_cost", native_unit_of_measurement="kr",
        suggested_display_precision=0, value_fn=lambda d: d["peak"]["cost"],
    ),
    SGFSensorDescription(
        key="model_confidence", translation_key="model_confidence",
        native_unit_of_measurement=PERCENTAGE, suggested_display_precision=0,
        value_fn=lambda d: round(d["model"]["confidence"] * 100),
    ),
    SGFSensorDescription(
        key="model_time_constant", translation_key="model_time_constant",
        native_unit_of_measurement=UnitOfTime.HOURS, suggested_display_precision=1,
        value_fn=lambda d: d["model"]["time_constant_h"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: SmartGridFlowCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [SGFSensor(coord, entry, d) for d in SENSORS]
    entities.append(SGFOverviewSensor(coord, entry))
    for key, name, _eid in coord._consumer_defs():
        entities.append(SGFConsumerSensor(coord, entry, key, name, "kwh_today", "Energi idag"))
        entities.append(SGFConsumerSensor(coord, entry, key, name, "cost_today", "Kostnad idag"))
        entities.append(SGFConsumerSensor(coord, entry, key, name, "power_kw", "Effekt"))
    async_add_entities(entities)


class SGFBase(CoordinatorEntity[SmartGridFlowCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coord: SmartGridFlowCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coord)
        self._entry = entry
        self._attr_device_info = device_info(entry)


class SGFSensor(SGFBase, SensorEntity):
    entity_description: SGFSensorDescription

    def __init__(self, coord, entry, description: SGFSensorDescription) -> None:
        super().__init__(coord, entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


class SGFConsumerSensor(SGFBase, SensorEntity):
    """Energi/kostnad/effekt per stor förbrukare."""

    def __init__(self, coord, entry, key: str, name: str, field: str, label: str) -> None:
        super().__init__(coord, entry)
        self._key, self._field = key, field
        self._attr_name = f"{name} {label.lower()}"
        self._attr_unique_id = f"{entry.entry_id}_{key}_{field}"
        if field == "kwh_today":
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
            self._attr_state_class = SensorStateClass.TOTAL
            self._attr_suggested_display_precision = 2
        elif field == "cost_today":
            self._attr_native_unit_of_measurement = "kr"
            self._attr_suggested_display_precision = 2
        else:
            self._attr_device_class = SensorDeviceClass.POWER
            self._attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
            self._attr_suggested_display_precision = 2

    @property
    def native_value(self):
        c = self.coordinator.consumers.get(self._key)
        if not c:
            return None
        return round(c.get(self._field, 0.0), 3)


class SGFOverviewSensor(SGFBase, SensorEntity):
    """Samlar allt som Lovelace-kortet visar i attributen.

    Stora attribut utesluts från databasen (recorder) för att hålla den liten.
    """

    _attr_translation_key = "overview"
    _unrecorded_attributes = frozenset(
        {"prices", "hp", "boiler", "consumers", "peak", "model", "price"}
    )

    def __init__(self, coord, entry) -> None:
        super().__init__(coord, entry)
        self._attr_unique_id = f"{entry.entry_id}_overview"

    @property
    def native_value(self):
        d = self.coordinator.data
        return d["price"]["level"] if d else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = dict(self.coordinator.data or {})
        d["sgf_overview"] = True  # används av kortet för att hitta sensorn
        return d
