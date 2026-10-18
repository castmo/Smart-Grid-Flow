"""Utbyggnadspunkt: generiska enheter (sol, batteri, elbilsladdare ...).

Idag drivs värmepump och varmvattenberedare direkt av koordinatorn. Nya enhetstyper
läggs till genom att implementera ``FlexDevice`` och registrera den i ``REGISTRY``.
Kortet och översiktssensorn ritar automatiskt alla förbrukare som rapporteras under
``consumers`` (nyckeln ``solar``/``battery``/``ev`` får egen ikon och flödesriktning).

Planerad ansvarsfördelning:

* ``SolarDevice``   – tillför prognosticerad produktion (kW) → sänker nettopriset
  för timmar med överskott; egenanvändning värderas till köppris, export till spotpris.
* ``BatteryDevice`` – laddar billiga timmar, urladdar dyra timmar / kapar effekttoppar
  (använder samma ``PeakTracker`` och prissteg som värmepumpen).
* ``EVChargerDevice`` – "X kWh klart före klockan Y": välj billigaste timmar via
  ``scheduler.cheapest_hours`` och respektera effekttoppströskeln.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from .optimizer import Step


@dataclass
class DeviceAction:
    """Vad enheten ska göra just nu."""

    on: bool | None = None
    power_kw: float | None = None
    setpoint: float | None = None
    reason: str = ""
    schedule: list[datetime] = field(default_factory=list)


class FlexDevice(ABC):
    """Basklass för en styrbar enhet som kan planeras mot elpriset."""

    key: str = "device"
    name: str = "Enhet"

    @abstractmethod
    def plan(self, now: datetime, steps: list[Step], state: dict) -> DeviceAction:
        """Beräkna nästa åtgärd givet prissteg och enhetens aktuella tillstånd."""


REGISTRY: dict[str, type[FlexDevice]] = {}


def register(cls: type[FlexDevice]) -> type[FlexDevice]:
    REGISTRY[cls.key] = cls
    return cls
