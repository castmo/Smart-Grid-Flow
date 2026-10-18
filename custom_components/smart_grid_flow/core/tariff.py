"""Elpris- och avgiftsberäkning (standard: Göteborg Energi, elområde SE3).

Alla belopp i SEK. Spotpriset från elbörsen anges exkl. moms; nätavgift och
energiskatt anges inkl. moms (så som de står i prislistan för privatkunder).
Kontrollera värdena mot din faktura / Göteborg Energis aktuella prislista.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class TariffConfig:
    """Alla avgifter som påverkar kostnaden per kWh och per månad."""

    vat: float = 0.25
    # Elhandlarens påslag (öppet pris + elcertifikat m.m.), öre/kWh exkl. moms.
    supplier_markup_ore: float = 5.0
    # Elnätets rörliga överföringsavgift, öre/kWh inkl. moms.
    grid_transfer_ore: float = 23.0
    # Energiskatt, öre/kWh inkl. moms.
    energy_tax_ore: float = 45.0
    # Effektavgift, kr per kW och månad inkl. moms.
    effect_price_kr_kw: float = 49.0
    # Antal högsta timmar (olika dygn) som medelvärdesbildas.
    effect_top_n: int = 3
    # Fast månadsavgift elnät + elhandel, kr/månad inkl. moms (endast statistik).
    fixed_fee_kr_month: float = 205.0

    def total_price(self, spot_ex_vat: float) -> float:
        """Totalt pris SEK/kWh inkl. moms, skatt och nätavgift."""
        energy = (spot_ex_vat + self.supplier_markup_ore / 100.0) * (1.0 + self.vat)
        return energy + self.grid_transfer_ore / 100.0 + self.energy_tax_ore / 100.0

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TariffConfig":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)
