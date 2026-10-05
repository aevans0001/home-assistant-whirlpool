"""Specialty (Download & Go) washer cycles for the DDM-proven WFW9620HBK3.

Kept in the integration so the library can stay pinned to 60e0867, whose
regular and utility cycle bodies are live-proven and must not change.

Evidence (model-specific washer DDM, retained in private research): each preset is a CapabilityData entry
``Cavity_CycleSetCycleName<Key>`` with an empty Required block and exactly
seven NonEditable attributes. set_specialty_cycle() writes those seven, in the
DDM's NonEditable order, in one send_attributes() call. It never writes
Cavity_OpSetOperations: selecting a Specialty cycle does not Start the washer.

CycleName is the preset's identity. SpecialtyCycleId is 1 for all eleven,
and Coats & Jackets and Lingerie share CycleSelect 70, so the current preset
is decoded from CycleName, never from CycleSelect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from whirlpool.washer import Washer

SPECIALTY_SUPPORTED_MODEL: Final = "WFW9620HBK3"

ATTR_TEMPERATURE: Final = "WashCavity_CycleSetTemperature"
ATTR_DOWNLOAD_AND_GO: Final = "Cavity_CycleSetDownloadAndGo"
ATTR_SOIL_LEVEL: Final = "WashCavity_CycleSetSoilLevel"
ATTR_CYCLE_SELECT: Final = "WashCavity_CycleSetCycleSelect"
ATTR_CYCLE_NAME: Final = "Cavity_CycleSetCycleName"
ATTR_SPIN_SPEED: Final = "WashCavity_CycleSetSpinSpeed"
ATTR_SPECIALTY_CYCLE_ID: Final = "Cavity_CycleSetSpecialtyCycleId"
ATTR_CHANGE_STATUS_CYCLE_SELECT: Final = "WashCavity_ChangeStatusCycleSelect"


@dataclass(frozen=True)
class SpecialtyPreset:
    """The fixed NonEditable values of one Specialty preset (wire values)."""

    cycle_name: str  # Cavity_CycleSetCycleName; not always the capability key
    cycle_select: int  # WashCavity_CycleSetCycleSelect enum
    temperature: int  # 0 Cold, 1 Cool, 2 Warm, 3 Hot, 4 ExtraHot
    spin_speed: int  # 2 Low, 3 Medium, 4 High, 5 ExtraHigh
    soil_level: int  # 0 Light, 1 Normal, 2 Heavy


# Ordered as the DDM's SetDownloadAndGo capability object lists them.
SPECIALTY_PRESETS: Final[dict[str, SpecialtyPreset]] = {
    "coats_jackets": SpecialtyPreset("Jackets", 70, 0, 4, 2),
    "diapers": SpecialtyPreset("Diapers", 92, 4, 5, 2),
    "sleeping_bags": SpecialtyPreset("SleepingBags", 22, 2, 3, 2),
    "comforters": SpecialtyPreset("Comforters", 90, 2, 3, 0),
    "machine_wash_curtains": SpecialtyPreset("Curtains", 44, 0, 3, 0),
    "swimwear": SpecialtyPreset("Swimwear", 65, 0, 3, 0),
    "activewear": SpecialtyPreset("Activewear", 1, 2, 5, 2),
    "jeans": SpecialtyPreset("Jeans", 11, 2, 5, 1),
    "blankets": SpecialtyPreset("Blankets", 50, 3, 5, 1),
    "lingerie": SpecialtyPreset("Lingerie", 70, 1, 2, 0),
    "business_casual": SpecialtyPreset("BusinessCasual", 16, 1, 4, 1),
}

SPECIALTY_OPTION_BY_CYCLE_NAME: Final[dict[str, str]] = {
    preset.cycle_name: option for option, preset in SPECIALTY_PRESETS.items()
}


def build_specialty_payload(option: str) -> dict[str, str]:
    """Return the exact seven-attribute body for ``option``.

    Raises ValueError for an unknown option.
    """
    preset = SPECIALTY_PRESETS.get(option)
    if preset is None:
        raise ValueError(f"Unknown specialty cycle: {option!r}")
    return {
        ATTR_DOWNLOAD_AND_GO: "1",
        ATTR_SPECIALTY_CYCLE_ID: "1",
        ATTR_CYCLE_SELECT: str(preset.cycle_select),
        ATTR_SOIL_LEVEL: str(preset.soil_level),
        ATTR_SPIN_SPEED: str(preset.spin_speed),
        ATTR_TEMPERATURE: str(preset.temperature),
        ATTR_CYCLE_NAME: preset.cycle_name,
    }


def is_specialty_model_supported(washer: Washer) -> bool:
    """Return whether the Specialty table applies to this washer model."""
    return washer.appliance_info.model_number == SPECIALTY_SUPPORTED_MODEL


def supports_specialty_cycles(washer: Washer) -> bool:
    """Return whether this washer exposes the Specialty cycle attributes."""
    return (
        is_specialty_model_supported(washer)
        and washer.has_attribute(ATTR_DOWNLOAD_AND_GO)
        and washer.has_attribute(ATTR_CYCLE_NAME)
        and washer.has_attribute(ATTR_CHANGE_STATUS_CYCLE_SELECT)
    )


def is_specialty_cycle_active(washer: Washer) -> bool:
    """Return whether a Specialty cycle is selected (DownloadAndGo == 1)."""
    return (
        is_specialty_model_supported(washer)
        and washer._get_attribute(ATTR_DOWNLOAD_AND_GO) == "1"
    )


def get_specialty_cycle(washer: Washer) -> str | None:
    """Return the active Specialty option key, or None.

    None when no Specialty cycle is active (idle reads DownloadAndGo=0,
    SpecialtyCycleId=0, CycleName="None"), and also for a CycleName that is
    not in the table, so cloud-side drift degrades instead of raising.
    """
    if not is_specialty_cycle_active(washer):
        return None
    cycle_name = washer._get_attribute(ATTR_CYCLE_NAME)
    return (
        None if cycle_name is None else SPECIALTY_OPTION_BY_CYCLE_NAME.get(cycle_name)
    )


async def set_specialty_cycle(washer: Washer, option: str) -> bool:
    """Select a Specialty cycle immediately, regardless of Remote Control.

    Raises ValueError for an unknown option before anything is sent. Returns
    False without sending when the washer does not support Specialty cycles
    or reports the cycle as not changeable right now.
    """
    payload = build_specialty_payload(option)
    if not supports_specialty_cycles(washer):
        return False
    if washer.cycle_select_changeable() is not True:
        return False
    return await washer.send_attributes(payload)
