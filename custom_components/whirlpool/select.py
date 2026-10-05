"""The select platform for Whirlpool Appliances."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from typing import Any, ClassVar, Final, override

from whirlpool.appliance import Appliance
from whirlpool.dryer import Dryer
from whirlpool.oven import Cavity as OvenCavity, CookMode, Oven
from whirlpool.washer import (
    WASH_SOIL_LEVEL_REVERSE,
    WASH_SPIN_SPEED_REVERSE,
    WASH_TEMPERATURE_REVERSE,
    Washer,
)

import voluptuous as vol

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    async_get_current_platform,
)

from . import WhirlpoolConfigEntry, favorites, specialty
from .const import DOMAIN
from .entity import WhirlpoolEntity, WhirlpoolOvenEntity

PARALLEL_UPDATES = 1

_LOGGER = logging.getLogger(__name__)

OVEN_COOK_MODES: Final[dict[CookMode, str]] = {
    CookMode.Standby: "standby",
    CookMode.Bake: "bake",
    CookMode.ConvectBake: "convection_bake",
    CookMode.Broil: "broil",
    CookMode.ConvectBroil: "convection_broil",
    CookMode.ConvectRoast: "convection_roast",
    CookMode.KeepWarm: "keep_warm",
    CookMode.AirFry: "air_fry",
}
OPTION_TO_OVEN_COOK_MODE: Final = {v: k for k, v in OVEN_COOK_MODES.items()}

# Target temperature (Celsius) used when a mode is selected while the oven is
# idle and has no target set yet.
DEFAULT_OVEN_TEMP = 175


WASHER_STEAM_OPTIONS: Final = ["off", "on"]
DRYER_WRINKLE_SHIELD_OPTIONS: Final = ["off", "on", "on_with_steam"]
WASHER_WHAT_OPTIONS: Final = ["regular", "colors", "whites", "towels", "delicates", "bulky"]
WASHER_HOW_OPTIONS: Final = [
    "normal",
    "quick",
    "wrinkle_control",
    "heavy_duty",
    "cold_wash",
    "sanitize",
]
# What/How pairs never offered for selection. Bulky+Sanitize has no DDM value.
# Colors+Cold Wash (wire 44) is valid and remains selectable.
HIDDEN_WASH_PAIRS: Final = frozenset({("bulky", "sanitize")})
DISPENSER_ENABLE_OPTIONS: Final = ["disabled", "enabled", "disabled_next_cycle"]
DISPENSER_CONCENTRATION_OPTIONS: Final = ["2x", "3x", "4x", "5x", "6x", "8x"]
DISPENSER_2_CONTENT_OPTIONS: Final = ["detergent", "softener"]

# Washer per-cycle option keys - DDM-proven on WFW9620HBK3. These are the FULL
# sets; each entity narrows them per selected cycle via its `options` property,
# because the DDM declares availability per cycle (for example Sanitize cycles
# offer only Extra Hot, and the Regular family omits Low spin).
WASHER_TEMPERATURE_OPTIONS: Final = ["cold", "cool", "warm", "hot", "extra_hot"]
WASHER_SPIN_SPEED_OPTIONS: Final = ["off", "low", "medium", "high", "extra_high"]
WASHER_SOIL_LEVEL_OPTIONS: Final = ["light", "normal", "heavy"]
WASHER_EXTRA_RINSE_OPTIONS: Final = ["off", "on"]
# Presoak is a fixed four-value DDM List (0 / 1800 / 3600 / 28800 seconds), not
# a range, so it is a select rather than a number entity.
WASHER_PRESOAK_OPTIONS: Final = ["off", "30_min", "1_hour", "8_hour"]
# Utility cycles: standalone cycle modes outside the What+How matrix, written
# to the same WashCavity_CycleSetCycleSelect attribute.
WASHER_UTILITY_CYCLE_OPTIONS: Final = ["drain_spin", "clean_washer"]
# Specialty (Download & Go) cycles - WFW9620HBK3 only. Ordered per the DDM's
# SetDownloadAndGo capability object (phase5c_ddm_results.json section 10273-10281).
WASHER_SPECIALTY_CYCLE_OPTIONS: Final = [
    "activewear",
    "blankets",
    "business_casual",
    "coats_jackets",
    "comforters",
    "diapers",
    "jeans",
    "lingerie",
    "machine_wash_curtains",
    "sleeping_bags",
    "swimwear",
]

# Dryer What+How options - DDM-proven on WED9620HBK2.
DRYER_WHAT_OPTIONS: Final = ["regular", "colors", "whites", "towels", "delicates", "bulky"]
# How options differ from washer: timed_dry replaces cold_wash.
DRYER_HOW_OPTIONS: Final = [
    "normal",
    "quick",
    "wrinkle_control",
    "heavy_duty",
    "sanitize",
    "timed_dry",
]
# Utility cycles: standalone cycle modes outside the What+How matrix.
DRYER_UTILITY_CYCLE_OPTIONS: Final = ["steam_refresh"]
# Dryness options - DDM-proven on WED9620HBK2 (values 1/4/7).
# DrynessNone (wire 10) exists in the DDM EnumValues definition but NEVER
# appears in any per-cycle Enumeration list - it is an internal/inapplicable
# state, not a user-selectable option. Excluded here; retained in
# DRYNESS_DISPLAY in dryer.py so live reads of wire "10" can still be decoded.
DRYER_DRYNESS_OPTIONS: Final = ["less", "normal", "more"]
# Manual dry time options - DDM-proven on WED9620HBK2.
# Options are PER-CYCLE-GROUP and must never be blended into a global union:
#   Quick-group cycles   -> 15 / 30 / 45 min  (wire: 900 / 1800 / 2700 s)
#   Timed-Dry-group cycles -> 30 / 60 / 90 min (wire: 1800 / 3600 / 5400 s)
# Any other cycle (non-MDT, unknown, missing) -> no options / entity unavailable.
# Use Dryer.get_manual_dry_time_options_minutes() to obtain the per-cycle list.
DRYER_MANUAL_DRY_TIME_QUICK_OPTIONS: Final = ["15", "30", "45"]
DRYER_MANUAL_DRY_TIME_TIMED_OPTIONS: Final = ["30", "60", "90"]
# Legacy union kept for decoding current_option only - do NOT expose as selectable options.
DRYER_MANUAL_DRY_TIME_OPTIONS: Final = ["15", "30", "45", "60", "90"]
# Temperature options - DDM-proven on WED9620HBK2 (values 0/1/2/5/8).
DRYER_TEMPERATURE_OPTIONS: Final = ["air", "cool_low", "cool_mid", "warm_mid", "hot_mid"]
# Static Guard and Eco Boost are boolean DDM attributes.
DRYER_TOGGLE_OPTIONS: Final = ["off", "on"]


@dataclass(frozen=True, kw_only=True)
class WhirlpoolSelectDescription(SelectEntityDescription):
    """Class describing Whirlpool select entities."""

    value_fn: Callable[[Appliance], str | None]
    set_fn: Callable[[Appliance, str], Awaitable[bool]]


REFRIGERATOR_DESCRIPTIONS: Final[tuple[WhirlpoolSelectDescription, ...]] = (
    WhirlpoolSelectDescription(
        key="refrigerator_temperature_level",
        translation_key="refrigerator_temperature_level",
        options=["-4", "-2", "0", "3", "5"],
        unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda fridge: (
            str(val) if (val := fridge.get_offset_temp()) is not None else None
        ),
        set_fn=lambda fridge, option: fridge.set_offset_temp(int(option)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: WhirlpoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the select platform."""
    appliances_manager = config_entry.runtime_data
    # All Favorites, including the optional starter, persist in HA storage.
    favorite_store = favorites.FavoriteStore(hass)
    await favorite_store.async_load()
    for washer in appliances_manager.washers:
        if washer.is_cycle_options_model_supported():
            await favorite_store.async_initialize_appliance("washer", washer.said)
    for dryer in appliances_manager.dryers:
        await favorite_store.async_initialize_appliance("dryer", dryer.said)

    entities: list[SelectEntity] = [
        WhirlpoolSelectEntity(refrigerator, description)
        for refrigerator in appliances_manager.refrigerators
        for description in REFRIGERATOR_DESCRIPTIONS
    ]
    entities.extend(
        WhirlpoolOvenCookModeSelect(oven, cavity)
        for oven in appliances_manager.ovens
        for cavity in (OvenCavity.Upper, OvenCavity.Lower)
        if oven.get_oven_cavity_exists(cavity)
    )
    # One Favorite/Specialty label per washer, created fresh on every
    # setup/reload so both selectors start at None (never resurrected from
    # stale Whirlpool CycleName/DownloadAndGo values). Every washer control
    # that changes a recipe-defining field reports to it.
    labels = {washer.said: CycleLabel() for washer in appliances_manager.washers}
    washer_entities: list[WhirlpoolWasherSelectBase] = []
    washer_entities.extend(WhirlpoolWasherWhatSelect(washer) for washer in appliances_manager.washers)
    washer_entities.extend(WhirlpoolWasherHowSelect(washer) for washer in appliances_manager.washers)
    washer_entities.extend(WhirlpoolWasherDispenserEnableSelect(washer, 1) for washer in appliances_manager.washers)
    washer_entities.extend(WhirlpoolWasherDispenserEnableSelect(washer, 2) for washer in appliances_manager.washers)
    washer_entities.extend(WhirlpoolWasherDispenserConcentrationSelect(washer, 1) for washer in appliances_manager.washers)
    washer_entities.extend(WhirlpoolWasherDispenserConcentrationSelect(washer, 2) for washer in appliances_manager.washers)
    washer_entities.extend(WhirlpoolWasherDispenser2ContentsSelect(washer) for washer in appliances_manager.washers)
    washer_entities.extend(
        WhirlpoolWasherFanFreshSelect(washer)
        for washer in appliances_manager.washers
        if washer.is_fan_fresh_model_supported()
    )
    washer_entities.extend(
        WhirlpoolWasherSteamSelect(washer)
        for washer in appliances_manager.washers
        if washer.is_steam_model_supported()
    )
    # Per-cycle washer options. Gated on the model the DDM capability table was
    # captured from: other washer models use different cycle numbering and
    # different option enums, so they keep their existing behaviour and simply
    # do not get these entities until their own DDM has been captured.
    washer_entities.extend(
        entity_class(washer)
        for washer in appliances_manager.washers
        if washer.is_cycle_options_model_supported()
        for entity_class in (
            WhirlpoolWasherTemperatureSelect,
            WhirlpoolWasherSpinSpeedSelect,
            WhirlpoolWasherSoilLevelSelect,
            WhirlpoolWasherExtraRinseSelect,
            WhirlpoolWasherPresoakSelect,
            WhirlpoolWasherUtilityCycleSelect,
        )
    )
    for entity in washer_entities:
        entity._label = labels[entity._appliance.said]
    entities.extend(washer_entities)
    # Specialty (Download & Go) lives in the integration (specialty.py) so the
    # library stays pinned to 60e0867 and regular/utility bodies are unchanged.
    entities.extend(
        WhirlpoolWasherSpecialtyCycleSelect(washer, labels[washer.said])
        for washer in appliances_manager.washers
        if specialty.is_specialty_model_supported(washer)
    )
    # HA-local Favorite recipes. These configure the washer but never Start it.
    entities.extend(
        WhirlpoolWasherFavoriteCycleSelect(washer, labels[washer.said], favorite_store)
        for washer in appliances_manager.washers
        if washer.is_cycle_options_model_supported()
    )

    # Dryer entities. One Favorite label per dryer, fresh on every setup/reload.
    dryer_labels = {dryer.said: CycleLabel() for dryer in appliances_manager.dryers}
    dryer_entities: list[WhirlpoolDryerSelectBase] = [
        entity_class(dryer)
        for dryer in appliances_manager.dryers
        for entity_class in (
            WhirlpoolDryerWrinkleShieldSelect,
            WhirlpoolDryerWhatSelect,
            WhirlpoolDryerHowSelect,
            WhirlpoolDryerUtilityCycleSelect,
            WhirlpoolDryerDrynessSelect,
            WhirlpoolDryerTemperatureSelect,
            WhirlpoolDryerStaticGuardSelect,
            WhirlpoolDryerEcoBoostSelect,
            WhirlpoolDryerManualDryTimeSelect,
        )
    ]
    for dryer_entity in dryer_entities:
        dryer_entity._label = dryer_labels[dryer_entity._appliance.said]
    entities.extend(dryer_entities)
    entities.extend(
        WhirlpoolDryerFavoriteCycleSelect(dryer, dryer_labels[dryer.said], favorite_store)
        for dryer in appliances_manager.dryers
    )
    async_add_entities(entities)

    # Favorite management actions, targeted at a Favorite Cycle select.
    platform = async_get_current_platform()
    for service, method in (
        (SERVICE_SAVE_FAVORITE, "async_save_favorite"),
        (SERVICE_DELETE_FAVORITE, "async_delete_favorite"),
    ):
        platform.async_register_entity_service(
            service, {vol.Required("name"): str}, _favorite_service(method)
        )


SERVICE_SAVE_FAVORITE: Final = "save_favorite"
SERVICE_DELETE_FAVORITE: Final = "delete_favorite"


def _favorite_service(method: str) -> Callable[..., Awaitable[None]]:
    """Return an entity-service handler that only accepts Favorite selects."""

    async def handler(entity: SelectEntity, call: Any) -> None:
        if not isinstance(entity, FavoriteSelectMixin):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_a_favorite_select"
            )
        await getattr(entity, method)(call.data["name"])

    return handler


class WhirlpoolSelectEntity(WhirlpoolEntity, SelectEntity):
    """Whirlpool select entity."""

    def __init__(
        self, appliance: Appliance, description: WhirlpoolSelectDescription
    ) -> None:
        """Initialize the select entity."""
        super().__init__(appliance, unique_id_suffix=f"-{description.key}")
        self.entity_description: WhirlpoolSelectDescription = description

    @override
    @property
    def current_option(self) -> str | None:
        """Retrieve currently selected option."""
        return self.entity_description.value_fn(self._appliance)

    @override
    async def async_select_option(self, option: str) -> None:
        """Set the selected option."""
        try:
            WhirlpoolSelectEntity._check_service_request(
                await self.entity_description.set_fn(self._appliance, option)
            )
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value_set",
            ) from err


class WhirlpoolOvenCookModeSelect(WhirlpoolOvenEntity, SelectEntity):
    """Settable cook mode for an oven cavity."""

    _attr_options = list(OVEN_COOK_MODES.values())

    def __init__(self, appliance: Oven, cavity: OvenCavity) -> None:
        """Initialize the oven cook mode select."""
        super().__init__(appliance, cavity, "oven_cook_mode", "-cook_mode")

    @override
    @property
    def current_option(self) -> str | None:
        """Return the current cook mode, if it is a selectable one."""
        return OVEN_COOK_MODES.get(self._appliance.get_cook_mode(self.cavity))

    @override
    async def async_select_option(self, option: str) -> None:
        """Set the cook mode, keeping the current/last target temperature."""
        mode = OPTION_TO_OVEN_COOK_MODE[option]
        try:
            if mode == CookMode.Standby:
                # Standby is the idle state: the oven reaches it by cancelling
                # the current cook, not by starting a "standby" cook.
                result = await self._appliance.stop_cook(self.cavity)
            else:
                target = self._appliance.get_target_temp(self.cavity)
                if target is None:
                    target = DEFAULT_OVEN_TEMP
                result = await self._appliance.set_cook(
                    target_temp=target,
                    mode=mode,
                    cavity=self.cavity,
                )
            WhirlpoolOvenCookModeSelect._check_service_request(result)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value_set",
            ) from err


# Recipe-defining fields a Favorite/Specialty label can be invalidated by.
FIELD_CYCLE: Final = "cycle"  # What / How / Utility: always defining
RECIPE_OPTION_FIELDS: Final = (
    "temperature",
    "spin_speed",
    "soil_level",
    "extra_rinse",
    "presoak",
    "fan_fresh",
    "steam",
)


class CycleLabel:
    """The Favorite or Specialty that Home Assistant last applied to one washer.

    Purely local UI state. Whirlpool can keep reporting an old DownloadAndGo /
    CycleName after another cycle has replaced a Specialty, so the washer's
    report never sets or clears this, and neither does any incoming update.
    It starts empty on every setup/reload, is set by a successful Favorite or
    Specialty apply, and is cleared only by a successful HA action that changes
    a field the applied recipe defines (see invalidate()).

    ``values`` maps each defining field to the recipe's option key, or to None
    when the recipe fixes that field only through the cycle's defaults (then
    any change clears the label).
    """

    def __init__(self) -> None:
        self.kind: str | None = None
        self.option = "none"
        self.values: dict[str, str | None] = {}
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def option_for(self, kind: str) -> str:
        return self.option if self.kind == kind else "none"

    def apply(self, kind: str, option: str, values: dict[str, str | None]) -> None:
        self.kind, self.option, self.values = kind, option, values
        self._notify()

    def clear(self) -> None:
        if self.kind is not None:
            self.kind, self.option, self.values = None, "none", {}
            self._notify()

    def invalidate(self, field: str, value: str | None = None) -> None:
        """Clear the label if ``field`` is recipe-defining and now differs."""
        if field == FIELD_CYCLE:
            self.clear()
        elif field in self.values:
            expected = self.values[field]
            if expected is None or value != expected:
                self.clear()

    def _notify(self) -> None:
        for listener in self._listeners:
            listener()


class WhirlpoolWasherSelectBase(WhirlpoolEntity, SelectEntity):
    """Base entity for statically proven WFW9620HBK3 washer settings."""

    _appliance: Washer

    def __init__(self, appliance: Washer, translation_key: str, suffix: str) -> None:
        super().__init__(appliance, unique_id_suffix=suffix)
        self._attr_translation_key = translation_key

    @staticmethod
    def _check(result: bool) -> None:
        WhirlpoolWasherSelectBase._check_service_request(result)

    def _require_remote_control(self) -> None:
        """Raise unless the appliance currently permits remote changes.

        Remote Control Enable is read-only in this fork - it can only be
        turned on at the appliance itself - so a disabled appliance gets a
        specific, actionable error rather than a generic failure.
        """
        if self._appliance.get_remote_control_enabled() is not True:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="remote_control_disabled",
                translation_placeholders={
                    "device_name": self._appliance.name or self._appliance.said
                },
            )

    @staticmethod
    def _invalid_value() -> ServiceValidationError:
        return ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_value_set"
        )

    def _wash_cycle_pair(self) -> tuple[str, str] | None:
        """Return the What/How pair decoded from the current CycleSelect."""
        return self._appliance.get_wash_cycle_pair()

    _label: CycleLabel | None = None

    def _invalidate(self, field: str, value: str | None = None) -> None:
        """Tell the Favorite/Specialty label a defining field was changed."""
        if self._label is not None:
            self._label.invalidate(field, value)


class WhirlpoolWasherCycleOptionSelect(WhirlpoolWasherSelectBase):
    """Base for the per-cycle washer option selects.

    Each subclass names the library predicates that describe its option, so the
    availability rule and the write path stay identical across all of them:

      * the model must be the one the DDM capability table was captured from
        and must actually report the attribute (`_supports`),
      * the CURRENTLY SELECTED cycle must offer the option at all
        (`_cycle_supports`) - Clean Washer with affresh, for instance, declares
        no options whatsoever, and Drain & Spin declares only spin, extra rinse
        and fan fresh,
      * the appliance must report the option as changeable right now
        (`_changeable`).

    `options` narrows to exactly the values the DDM declares legal for the
    selected cycle, so the UI never offers a value that would be rejected at
    Start. Where a cycle locks an option to a single value (every Sanitize
    cycle locks temperature to Extra Hot) the select correctly shows one option.
    """

    _all_options: list[str] = []
    _field: str = ""  # recipe field this option defines (see CycleLabel)

    def _supports(self) -> bool:
        raise NotImplementedError

    def _cycle_supports(self) -> bool:
        raise NotImplementedError

    def _changeable(self) -> bool | None:
        raise NotImplementedError

    def _supported_options(self) -> list[str]:
        raise NotImplementedError

    async def _set(self, option: str) -> bool:
        raise NotImplementedError

    @property
    def options(self) -> list[str]:
        """Return only the option keys legal for the selected cycle."""
        return self._supported_options() or self._all_options

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._supports()
            and self._cycle_supports()
            and self._changeable() is True
        )

    async def async_select_option(self, option: str) -> None:
        """Write the option after re-checking every live safety gate."""
        if not self._supports() or self._changeable() is not True:
            raise self._invalid_value()
        try:
            self._check(await self._set(option))
        except ValueError as err:
            # The library rejects values that are illegal for the selected
            # cycle before anything is sent, because the cloud API would
            # otherwise accept them and only the appliance would refuse, at
            # Start.
            raise self._invalid_value() from err
        self._invalidate(self._field, option)


class WhirlpoolWasherFanFreshSelect(WhirlpoolWasherSelectBase):
    """Fan Fresh control for the DDM-proven WFW9620HBK3 washer only."""

    _attr_options = ["off", "on"]

    def __init__(self, appliance: Washer) -> None:
        super().__init__(appliance, "washer_fan_fresh", "-fan_fresh")

    @property
    def available(self) -> bool:
        """Return whether the appliance currently permits Fan Fresh changes.

        Adds the per-cycle DDM gate to the existing checks: Clean Washer with
        affresh declares no Fan Fresh option. Every normal cycle and Drain &
        Spin do declare it, so no previously available cycle is affected.
        """
        return (
            super().available
            and self._appliance.supports_fan_fresh()
            and self._appliance.cycle_supports_fan_fresh()
            and self._appliance.fan_fresh_changeable() is True
        )

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_fan_fresh()

    async def async_select_option(self, option: str) -> None:
        """Set Fan Fresh after rechecking the live appliance safety gates."""
        if (
            not self._appliance.supports_fan_fresh()
            or self._appliance.fan_fresh_changeable() is not True
        ):
            raise self._invalid_value()
        try:
            self._check(await self._appliance.set_fan_fresh(option))
        except ValueError as err:
            raise self._invalid_value() from err
        self._invalidate("fan_fresh", option)


class WhirlpoolWasherSteamSelect(WhirlpoolWasherSelectBase):
    """Steam Enable control for the DDM-proven WFW9620HBK3 washer only."""

    _attr_options = WASHER_STEAM_OPTIONS

    def __init__(self, appliance: Washer) -> None:
        super().__init__(appliance, "washer_steam", "-steam")

    @property
    def available(self) -> bool:
        """Return whether the appliance currently permits Steam Enable changes.

        Adds the per-cycle DDM gate: Cavity_CycleSetSteamEnable is absent from
        Cold Wash (18), from every What+ColdWash variant (44/50/65/82/88), and
        from both utility cycles. It IS present on all Sanitize variants.
        """
        return (
            super().available
            and self._appliance.supports_steam()
            and self._appliance.cycle_supports_steam()
            and self._appliance.steam_changeable() is True
        )

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_steam()

    async def async_select_option(self, option: str) -> None:
        """Set Steam Enable after rechecking the live appliance safety gates."""
        if (
            not self._appliance.supports_steam()
            or self._appliance.steam_changeable() is not True
        ):
            raise self._invalid_value()
        try:
            self._check(await self._appliance.set_steam(option))
        except ValueError as err:
            raise self._invalid_value() from err
        self._invalidate("steam", option)


class WhirlpoolWasherWhatSelect(WhirlpoolWasherSelectBase):
    _attr_options = WASHER_WHAT_OPTIONS

    def __init__(self, appliance: Washer, label: CycleLabel | None = None) -> None:
        super().__init__(appliance, "washer_what_to_wash", "-what_to_wash")
        self._label = label

    @property
    def current_option(self) -> str | None:
        """Return the 'what' half of the current cycle.

        None for a utility cycle, which is outside the What+How matrix.
        """
        pair = self._wash_cycle_pair()
        return None if pair is None else pair[0]

    async def async_select_option(self, option: str) -> None:
        pair = self._wash_cycle_pair()
        how = "normal" if pair is None else pair[1]
        # Bulky+Sanitize has no DDM value, and the Whirlpool app does not offer
        # Colors+Cold Wash; fall back to Normal rather than sending either.
        if (option, how) in HIDDEN_WASH_PAIRS:
            how = "normal"
        try:
            self._check(await self._appliance.set_wash_cycle_pair(option, how))
        except ValueError as err:
            raise self._invalid_value() from err
        self._invalidate(FIELD_CYCLE)


class WhirlpoolWasherHowSelect(WhirlpoolWasherSelectBase):
    def __init__(self, appliance: Washer, label: CycleLabel | None = None) -> None:
        super().__init__(appliance, "washer_how_to_wash", "-how_to_wash")
        self._label = label

    @property
    def options(self) -> list[str]:
        pair = self._wash_cycle_pair()
        if pair is None:
            return WASHER_HOW_OPTIONS
        # Keep a hidden pair listed only while the washer actually reports it
        # (e.g. Curtains' base cycle 44), so the current state still displays.
        return [
            how
            for how in WASHER_HOW_OPTIONS
            if (pair[0], how) not in HIDDEN_WASH_PAIRS or how == pair[1]
        ]

    @property
    def current_option(self) -> str | None:
        """Return the 'how' half of the current cycle, or None for a utility cycle."""
        pair = self._wash_cycle_pair()
        return None if pair is None else pair[1]

    async def async_select_option(self, option: str) -> None:
        pair = self._wash_cycle_pair()
        what = "regular" if pair is None else pair[0]
        if (what, option) in HIDDEN_WASH_PAIRS:
            raise self._invalid_value()
        try:
            self._check(await self._appliance.set_wash_cycle_pair(what, option))
        except ValueError as err:
            raise self._invalid_value() from err
        self._invalidate(FIELD_CYCLE)


class WhirlpoolWasherDispenserEnableSelect(WhirlpoolWasherSelectBase):
    _attr_options = DISPENSER_ENABLE_OPTIONS

    def __init__(self, appliance: Washer, dispenser: int) -> None:
        self._dispenser = dispenser
        super().__init__(
            appliance,
            f"washer_dispenser_{dispenser}_enable",
            f"-dispenser_{dispenser}_enable",
        )

    @property
    def current_option(self) -> str | None:
        return (
            self._appliance.get_dispense_1_enable()
            if self._dispenser == 1
            else self._appliance.get_dispense_2_enable()
        )

    async def async_select_option(self, option: str) -> None:
        result = (
            await self._appliance.set_dispense_1_enable(option)
            if self._dispenser == 1
            else await self._appliance.set_dispense_2_enable(option)
        )
        self._check(result)
        self._invalidate(f"dispenser_{self._dispenser}_enable", option)


class WhirlpoolWasherDispenserConcentrationSelect(WhirlpoolWasherSelectBase):
    _attr_options = DISPENSER_CONCENTRATION_OPTIONS

    def __init__(self, appliance: Washer, dispenser: int) -> None:
        self._dispenser = dispenser
        super().__init__(
            appliance,
            f"washer_dispenser_{dispenser}_concentration",
            f"-dispenser_{dispenser}_concentration",
        )

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        enabled = (
            self._appliance.get_dispense_1_enable()
            if self._dispenser == 1
            else self._appliance.get_dispense_2_enable()
        )
        if enabled != "enabled":
            return False
        return not (
            self._dispenser == 2
            and self._appliance.get_dispense_2_selection() == "softener"
        )

    @property
    def current_option(self) -> str | None:
        return (
            self._appliance.get_dispense_1_concentration()
            if self._dispenser == 1
            else self._appliance.get_dispense_2_concentration()
        )

    async def async_select_option(self, option: str) -> None:
        result = (
            await self._appliance.set_dispense_1_concentration(option)
            if self._dispenser == 1
            else await self._appliance.set_dispense_2_concentration(option)
        )
        self._check(result)
        self._invalidate(f"dispenser_{self._dispenser}_concentration", option)


class WhirlpoolWasherDispenser2ContentsSelect(WhirlpoolWasherSelectBase):
    _attr_options = DISPENSER_2_CONTENT_OPTIONS

    def __init__(self, appliance: Washer) -> None:
        super().__init__(appliance, "washer_dispenser_2_contents", "-dispenser_2_contents")

    @property
    def available(self) -> bool:
        return super().available and self._appliance.get_dispense_2_enable() == "enabled"

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_dispense_2_selection()

    async def async_select_option(self, option: str) -> None:
        self._check(await self._appliance.set_dispense_2_selection(option))
        self._invalidate("dispenser_2_contents", option)


class WhirlpoolWasherTemperatureSelect(WhirlpoolWasherCycleOptionSelect):
    """Wash temperature for the DDM-proven WFW9620HBK3 washer.

    Wire values 0-4 (Cold / Cool / Warm / Hot / Extra Hot). The DDM narrows
    the enumeration for exactly one family of cycles: all five Sanitize cycles
    (3/48/69/86/92) list Extra Hot only. Drain & Spin and Clean Washer declare
    no temperature at all, so the entity goes unavailable for them.
    """

    _all_options = WASHER_TEMPERATURE_OPTIONS
    _field = "temperature"

    def __init__(self, appliance: Washer) -> None:
        super().__init__(appliance, "washer_temperature", "-temperature")

    def _supports(self) -> bool:
        return self._appliance.supports_temperature()

    def _cycle_supports(self) -> bool:
        return self._appliance.cycle_supports_temperature()

    def _changeable(self) -> bool | None:
        return self._appliance.temperature_changeable()

    def _supported_options(self) -> list[str]:
        return self._appliance.get_supported_temperatures()

    async def _set(self, option: str) -> bool:
        return await self._appliance.set_temperature(option)

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_temperature()


class WhirlpoolWasherSpinSpeedSelect(WhirlpoolWasherCycleOptionSelect):
    """Spin speed for the DDM-proven WFW9620HBK3 washer.

    Wire values are 0/2/3/4/5 - there is no wire value 1, so a caller cannot
    reach one through this entity. The five Regular-family cycles (1/2/3/4/18)
    omit Low; every other cycle that spins offers all five. Clean Washer
    declares no spin speed at all; Drain & Spin requires one.
    """

    _all_options = WASHER_SPIN_SPEED_OPTIONS
    _field = "spin_speed"

    def __init__(self, appliance: Washer) -> None:
        super().__init__(appliance, "washer_spin_speed", "-spin_speed")

    def _supports(self) -> bool:
        return self._appliance.supports_spin_speed()

    def _cycle_supports(self) -> bool:
        return self._appliance.cycle_supports_spin_speed()

    def _changeable(self) -> bool | None:
        return self._appliance.spin_speed_changeable()

    def _supported_options(self) -> list[str]:
        return self._appliance.get_supported_spin_speeds()

    async def _set(self, option: str) -> bool:
        return await self._appliance.set_spin_speed(option)

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_spin_speed()


class WhirlpoolWasherSoilLevelSelect(WhirlpoolWasherCycleOptionSelect):
    """Soil level for the DDM-proven WFW9620HBK3 washer.

    Wire values 0/1/2 (Light / Normal / Heavy). Every normal cycle offers all
    three; both utility cycles offer none.
    """

    _all_options = WASHER_SOIL_LEVEL_OPTIONS
    _field = "soil_level"

    def __init__(self, appliance: Washer) -> None:
        super().__init__(appliance, "washer_soil_level", "-soil_level")

    def _supports(self) -> bool:
        return self._appliance.supports_soil_level()

    def _cycle_supports(self) -> bool:
        return self._appliance.cycle_supports_soil_level()

    def _changeable(self) -> bool | None:
        return self._appliance.soil_level_changeable()

    def _supported_options(self) -> list[str]:
        return self._appliance.get_supported_soil_levels()

    async def _set(self, option: str) -> bool:
        return await self._appliance.set_soil_level(option)

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_soil_level()


class WhirlpoolWasherExtraRinseSelect(WhirlpoolWasherCycleOptionSelect):
    """Extra rinse for the DDM-proven WFW9620HBK3 washer.

    Implemented as a select (off/on) rather than a switch, matching the
    existing Static Guard and Eco Boost dryer controls, because this fork has
    no switch platform. Available on every normal cycle and on Drain & Spin;
    Clean Washer with affresh declares no extra rinse.
    """

    _all_options = WASHER_EXTRA_RINSE_OPTIONS
    _field = "extra_rinse"

    def __init__(self, appliance: Washer) -> None:
        super().__init__(appliance, "washer_extra_rinse", "-extra_rinse")

    def _supports(self) -> bool:
        return self._appliance.supports_extra_rinse()

    def _cycle_supports(self) -> bool:
        return self._appliance.cycle_supports_extra_rinse()

    def _changeable(self) -> bool | None:
        return self._appliance.extra_rinse_changeable()

    def _supported_options(self) -> list[str]:
        return self._appliance.get_supported_extra_rinse_options()

    async def _set(self, option: str) -> bool:
        return await self._appliance.set_extra_rinse(option)

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_extra_rinse()


class WhirlpoolWasherPresoakSelect(WhirlpoolWasherCycleOptionSelect):
    """Presoak timer for the DDM-proven WFW9620HBK3 washer.

    The DDM declares presoak as a four-value List in seconds
    (0 / 1800 / 3600 / 28800), not a range, which is why this is a select and
    not a number entity - a number entity would imply arbitrary values the
    appliance does not accept. Absent from all five Sanitize cycles and from
    both utility cycles.
    """

    _all_options = WASHER_PRESOAK_OPTIONS
    _field = "presoak"

    def __init__(self, appliance: Washer) -> None:
        super().__init__(appliance, "washer_presoak", "-presoak")

    def _supports(self) -> bool:
        return self._appliance.supports_presoak()

    def _cycle_supports(self) -> bool:
        return self._appliance.cycle_supports_presoak()

    def _changeable(self) -> bool | None:
        return self._appliance.presoak_changeable()

    def _supported_options(self) -> list[str]:
        return self._appliance.get_supported_presoak_options()

    async def _set(self, option: str) -> bool:
        return await self._appliance.set_presoak(option)

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_presoak()


class WhirlpoolWasherUtilityCycleSelect(WhirlpoolWasherSelectBase):
    """Utility cycle select for the DDM-proven WFW9620HBK3 washer.

    Exposes the two standalone cycle modes that sit outside the What+How
    matrix: Drain & Spin (CycleSelect=8) and Clean Washer with affresh
    (CycleSelect=20). Both are reached through the DDM's separate
    SetUtilityCycle capability but are written to the same CycleSelect wire
    attribute, so selecting a normal What/How cycle leaves the utility cycle
    again - the same relationship the dryer's utility cycle select already has.

    current_option is None while a normal cycle is selected, and the What/How
    selects report None while a utility cycle is selected, so neither ever
    claims a value that is not really set.

    Note that the DDM rule engine (rule W6) excludes Clean Washer from the
    Modify command, so a running Clean Washer cycle cannot be altered
    remotely - it can still be cancelled.
    """

    _attr_options = WASHER_UTILITY_CYCLE_OPTIONS

    def __init__(self, appliance: Washer, label: CycleLabel | None = None) -> None:
        super().__init__(appliance, "washer_utility_cycle", "-utility_cycle")
        self._label = label

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._appliance.supports_utility_cycles()
            and self._appliance.cycle_select_changeable() is True
        )

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_utility_cycle()

    async def async_select_option(self, option: str) -> None:
        if self._appliance.cycle_select_changeable() is not True:
            raise self._invalid_value()
        try:
            self._check(await self._appliance.set_utility_cycle(option))
        except ValueError as err:
            raise self._invalid_value() from err
        self._invalidate(FIELD_CYCLE)


class WhirlpoolWasherSpecialtyCycleSelect(WhirlpoolWasherSelectBase):
    """Specialty cycle selector on the WFW9620HBK3 washer.

    Writes the preset's seven DDM NonEditable attributes in one immediate
    send_attributes() call (see specialty.py), whether Remote Control is on or
    off, exactly like What/How and utility selection. HA sends no operation:
    Start stays on the Start button and its Remote Control gate.

    current_option comes from the shared CycleLabel: the Specialty HA last
    applied, kept while it still describes the configuration. It starts at
    None on every setup/reload and is never derived from Whirlpool's
    CycleName/DownloadAndGo, which can stay stale after another cycle replaces
    the Specialty. Changing What/How, Utility, a Favorite, or any cycle option
    in HA clears it; another Specialty replaces it.

    Evidence: model-specific DDM capability capture retained in private research.
    """

    _attr_options: ClassVar[list[str]] = ["none", *WASHER_SPECIALTY_CYCLE_OPTIONS]

    def __init__(self, appliance: Washer, label: CycleLabel | None = None) -> None:
        super().__init__(appliance, "washer_specialty_cycle", "-specialty_cycle")
        self._label = label if label is not None else CycleLabel()
        self._label.add_listener(self._label_changed)

    def _label_changed(self) -> None:
        if getattr(self, "hass", None) is not None:
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return (
            super().available
            and specialty.supports_specialty_cycles(self._appliance)
            and self._appliance.cycle_select_changeable() is True
        )

    @property
    def current_option(self) -> str | None:
        assert self._label is not None
        return self._label.option_for("specialty")

    async def async_select_option(self, option: str) -> None:
        assert self._label is not None
        if option == "none":
            if self._label.kind == "specialty":
                self._label.clear()
            return
        preset = specialty.SPECIALTY_PRESETS.get(option)
        if preset is None:
            raise self._invalid_value()
        if self._appliance.cycle_select_changeable() is not True:
            raise self._invalid_value()
        try:
            self._check(await specialty.set_specialty_cycle(self._appliance, option))
        except ValueError as err:
            raise self._invalid_value() from err
        self._label.apply(
            "specialty",
            option,
            {
                "temperature": WASH_TEMPERATURE_REVERSE.get(preset.temperature),
                "spin_speed": WASH_SPIN_SPEED_REVERSE.get(preset.spin_speed),
                "soil_level": WASH_SOIL_LEVEL_REVERSE.get(preset.soil_level),
                "extra_rinse": None,
                "presoak": None,
                "fan_fresh": None,
                "steam": None,
            },
        )


class FavoriteSelectMixin:
    """Favorite handling shared by the washer and dryer Favorite selects.

    Options are all stored Favorites; none is protected from deletion.
    current_option comes from the appliance's CycleLabel: a Favorite stays
    shown while its recipe still describes the configuration and clears when
    an HA action changes a field the recipe defines. Incoming Whirlpool
    updates never change it.
    """

    _kind: str
    _store: favorites.FavoriteStore | None
    _label: CycleLabel | None
    _appliance: Any

    def _init_favorites(
        self, label: CycleLabel | None, store: favorites.FavoriteStore | None
    ) -> None:
        self._label = label if label is not None else CycleLabel()
        self._label.add_listener(self._label_changed)
        self._store = store

    def _label_changed(self) -> None:
        if getattr(self, "hass", None) is not None:
            self.async_write_ha_state()  # type: ignore[attr-defined]

    def _stored_favorites(self) -> dict[str, Any]:
        if self._store is None:
            return {}
        return self._store.favorites(self._kind, self._appliance.said)

    @property
    def options(self) -> list[str]:
        """Return None followed by every stored Favorite."""
        return ["none", *self._stored_favorites()]

    @property
    def current_option(self) -> str | None:
        assert self._label is not None
        return self._label.option_for("favorite")

    def _recipe(self, option: str) -> Any:
        return self._stored_favorites().get(option)

    def _capture(self) -> Any:
        """Return a recipe for the current configuration (ValueError if none)."""
        raise NotImplementedError

    def _label_values(self, recipe: Any) -> dict[str, str | None]:
        raise NotImplementedError

    async def async_save_favorite(self, name: str) -> None:
        """Save the current configuration as a Favorite called ``name``.

        A Favorite with the same name (ignoring case) is replaced. Sends
        nothing to the appliance.
        """
        assert self._label is not None
        try:
            cleaned = favorites.normalize_name(name)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="favorite_name_invalid"
            ) from err
        if self._store is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="request_failed"
            )
        try:
            recipe = self._capture()
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="favorite_unsupported_cycle"
            ) from err
        stored = await self._store.async_save(
            self._kind, self._appliance.said, cleaned, recipe
        )
        # The current configuration is, by definition, this Favorite.
        self._label.apply("favorite", stored, self._label_values(recipe))

    async def async_delete_favorite(self, name: str) -> None:
        """Delete any stored Favorite, including the optional starter."""
        assert self._label is not None
        cleaned = " ".join(str(name).split())
        if self._store is None or not await self._store.async_delete(
            self._kind, self._appliance.said, cleaned
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="favorite_not_found"
            )
        if (
            self._label.kind == "favorite"
            and self._label.option.casefold() == cleaned.casefold()
        ):
            self._label.clear()
        else:
            self._label_changed()  # the option list changed


class WhirlpoolWasherFavoriteCycleSelect(FavoriteSelectMixin, WhirlpoolWasherSelectBase):
    """Apply or save a Home Assistant-local washer Favorite recipe.

    The label clears on What/How, Utility, Specialty, any cycle option, or a
    dispenser setting the recipe sets.
    """

    _kind = "washer"

    def __init__(
        self,
        appliance: Washer,
        label: CycleLabel | None = None,
        store: favorites.FavoriteStore | None = None,
    ) -> None:
        super().__init__(appliance, "washer_favorite_cycle", "-favorite_cycle")
        self._init_favorites(label, store)

    @property
    def available(self) -> bool:
        """Return whether a Favorite can currently configure the washer."""
        return (
            super().available
            and self._appliance.is_cycle_options_model_supported()
            and self._appliance.cycle_select_changeable() is True
        )

    def _capture(self) -> favorites.WasherFavorite:
        assert self._label is not None
        if self._label.kind == "specialty":
            # A Specialty is not a What/How recipe and cannot be stored as one.
            raise ValueError("A Specialty cycle cannot be saved as a Favorite")
        return favorites.capture_washer_favorite(self._appliance)

    def _label_values(self, recipe: favorites.WasherFavorite) -> dict[str, str | None]:
        values: dict[str, str | None] = {
            "temperature": recipe.temperature,
            "spin_speed": recipe.spin_speed,
            "soil_level": recipe.soil_level,
            "extra_rinse": recipe.extra_rinse,
            "presoak": recipe.presoak,
            "fan_fresh": recipe.fan_fresh,
            "steam": recipe.steam,
        }
        for field in ("dispenser_1_enable", "dispenser_2_enable", "dispenser_2_contents"):
            value = getattr(recipe, field)
            if value is not None:
                values[field] = value
        return values

    async def async_select_option(self, option: str) -> None:
        """Apply the selected local recipe without starting the washer."""
        assert self._label is not None
        if option == "none":
            if self._label.kind == "favorite":
                self._label.clear()
            return

        recipe = self._recipe(option)
        if recipe is None:
            raise self._invalid_value()

        if self._appliance.cycle_select_changeable() is not True:
            raise self._invalid_value()

        try:
            self._check(
                await self._appliance.set_wash_cycle_recipe(
                    recipe.what,
                    recipe.how,
                    temperature=recipe.temperature,
                    soil_level=recipe.soil_level,
                    spin_speed=recipe.spin_speed,
                    presoak=recipe.presoak,
                    extra_rinse=recipe.extra_rinse,
                    fan_fresh=recipe.fan_fresh,
                    steam=recipe.steam,
                )
            )
            # The cycle is now replaced, whatever happens to the dispensers.
            self._label.clear()

            if recipe.dispenser_1_enable is not None:
                self._check(
                    await self._appliance.set_dispense_1_enable(
                        recipe.dispenser_1_enable
                    )
                )

            if recipe.dispenser_2_contents is not None:
                self._check(
                    await self._appliance.set_dispense_2_selection(
                        recipe.dispenser_2_contents
                    )
                )

            if recipe.dispenser_2_enable is not None:
                self._check(
                    await self._appliance.set_dispense_2_enable(
                        recipe.dispenser_2_enable
                    )
                )
        except ValueError as err:
            raise self._invalid_value() from err

        self._label.apply("favorite", option, self._label_values(recipe))


class WhirlpoolDryerSelectBase(WhirlpoolEntity, SelectEntity):
    """Base entity for DDM-proven dryer settings."""

    def __init__(self, appliance: Dryer, translation_key: str, suffix: str) -> None:
        super().__init__(appliance, unique_id_suffix=suffix)
        self._attr_translation_key = translation_key

    @staticmethod
    def _check(result: bool) -> None:
        WhirlpoolDryerSelectBase._check_service_request(result)

    _label: CycleLabel | None = None

    def _invalidate(self, field: str, value: str | None = None) -> None:
        """Tell the dryer's Favorite label a defining field was changed."""
        if self._label is not None:
            self._label.invalidate(field, value)


class WhirlpoolDryerWrinkleShieldSelect(WhirlpoolDryerSelectBase):
    """WrinkleShield control (off / on / on_with_steam) for the DDM-proven WED9620HBK2 dryer."""

    _attr_options = DRYER_WRINKLE_SHIELD_OPTIONS

    def __init__(self, appliance: Dryer) -> None:
        super().__init__(appliance, "dryer_wrinkle_shield", "-wrinkle_shield")

    @property
    def available(self) -> bool:
        """Return whether the appliance currently permits WrinkleShield changes."""
        return (
            super().available
            and self._appliance.get_wrinkle_shield_changeable() is True
        )

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_wrinkle_shield_str()

    async def async_select_option(self, option: str) -> None:
        """Set WrinkleShield after rechecking the live appliance safety gates."""
        if self._appliance.get_wrinkle_shield_changeable() is not True:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            )
        self._check(await self._appliance.set_wrinkle_shield(option))
        self._invalidate("wrinkle_shield", option)


class WhirlpoolDryerWhatSelect(WhirlpoolDryerSelectBase):
    """'What to Dry' cycle category for the DDM-proven WED9620HBK2 dryer.

    Selects the 'what' dimension of the What+How matrix. Changing 'what'
    keeps the current 'how' unless the new combination is forbidden, in which
    case 'how' falls back to 'normal'.
    """

    _attr_options = DRYER_WHAT_OPTIONS

    def __init__(self, appliance: Dryer) -> None:
        super().__init__(appliance, "dryer_what_to_dry", "-what_to_dry")

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._appliance.get_cycle_changeable() is True
        )

    @property
    def current_option(self) -> str | None:
        pair = self._appliance.get_dry_cycle_pair()
        return None if pair is None else pair[0]

    async def async_select_option(self, option: str) -> None:
        if self._appliance.get_cycle_changeable() is not True:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            )
        pair = self._appliance.get_dry_cycle_pair()
        how = "normal" if pair is None else pair[1]
        # Delicates+Sanitize is DDM-forbidden; fall back to 'normal'.
        if option == "delicates" and how == "sanitize":
            how = "normal"
        try:
            self._check(await self._appliance.set_dry_cycle_pair(option, how))
            self._invalidate(FIELD_CYCLE)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            ) from err


class WhirlpoolDryerHowSelect(WhirlpoolDryerSelectBase):
    """'How to Dry' method for the DDM-proven WED9620HBK2 dryer.

    Selects the 'how' dimension of the What+How matrix. Delicates+Sanitize
    is DDM-forbidden and is excluded from 'how' options when 'what' is
    'delicates', matching the rule enforced by set_dry_cycle_pair().
    """

    def __init__(self, appliance: Dryer) -> None:
        super().__init__(appliance, "dryer_how_to_dry", "-how_to_dry")

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._appliance.get_cycle_changeable() is True
        )

    @property
    def options(self) -> list[str]:
        """Exclude Sanitize when 'what' is 'delicates' - DDM-forbidden."""
        pair = self._appliance.get_dry_cycle_pair()
        if pair is not None and pair[0] == "delicates":
            return [o for o in DRYER_HOW_OPTIONS if o != "sanitize"]
        return DRYER_HOW_OPTIONS

    @property
    def current_option(self) -> str | None:
        pair = self._appliance.get_dry_cycle_pair()
        return None if pair is None else pair[1]

    async def async_select_option(self, option: str) -> None:
        if self._appliance.get_cycle_changeable() is not True:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            )
        pair = self._appliance.get_dry_cycle_pair()
        what = "regular" if pair is None else pair[0]
        if what == "delicates" and option == "sanitize":
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            )
        try:
            self._check(await self._appliance.set_dry_cycle_pair(what, option))
            self._invalidate(FIELD_CYCLE)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            ) from err


class WhirlpoolDryerUtilityCycleSelect(WhirlpoolDryerSelectBase):
    """Utility cycle select for the DDM-proven WED9620HBK2 dryer.

    Exposes standalone cycle modes that are outside the What+How matrix.
    Currently only Steam Refresh (CycleSelect=10) is DDM-proven.
    Steam Refresh is a separate cycle - NOT the same as WrinkleShield=2
    (On with Steam), which is a post-cycle tumble option.
    current_option is None when no utility cycle is active.
    """

    _attr_options = DRYER_UTILITY_CYCLE_OPTIONS

    def __init__(self, appliance: Dryer) -> None:
        super().__init__(appliance, "dryer_utility_cycle", "-utility_cycle")

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._appliance.get_cycle_changeable() is True
        )

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_utility_cycle()

    async def async_select_option(self, option: str) -> None:
        if self._appliance.get_cycle_changeable() is not True:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            )
        try:
            self._check(await self._appliance.set_utility_cycle(option))
            self._invalidate(FIELD_CYCLE)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            ) from err


class WhirlpoolDryerDrynessSelect(WhirlpoolDryerSelectBase):
    """Dryness level select for the DDM-proven WED9620HBK2 dryer.

    DDM-proven user-selectable values: less (1), normal (4), more (7).
    Wire value 10 (DDM label 'None') is excluded - it never appears in any
    per-cycle Enumeration list and is not a user-selectable option.
    """

    _attr_options = DRYER_DRYNESS_OPTIONS

    def __init__(self, appliance: Dryer) -> None:
        super().__init__(appliance, "dryer_dryness", "-dryness")

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._appliance.get_dryness_changeable() is True
        )

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_dryness_str()

    async def async_select_option(self, option: str) -> None:
        if self._appliance.get_dryness_changeable() is not True:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            )
        self._check(await self._appliance.set_dryness(option))
        self._invalidate("dryness", option)


class WhirlpoolDryerTemperatureSelect(WhirlpoolDryerSelectBase):
    """Temperature select for the DDM-proven WED9620HBK2 dryer.

    DDM-proven values: air (0), cool_low (1), cool_mid (2), warm_mid (5), hot_mid (8).
    """

    _attr_options = DRYER_TEMPERATURE_OPTIONS

    def __init__(self, appliance: Dryer) -> None:
        super().__init__(appliance, "dryer_temperature", "-temperature")

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._appliance.get_temperature_changeable() is True
        )

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_temperature_str()

    async def async_select_option(self, option: str) -> None:
        if self._appliance.get_temperature_changeable() is not True:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            )
        self._check(await self._appliance.set_temperature(option))
        self._invalidate("temperature", option)


class WhirlpoolDryerStaticGuardSelect(WhirlpoolDryerSelectBase):
    """Static Guard control for the DDM-proven WED9620HBK2 dryer.

    Implemented as a select (off/on) because no switch.py exists in this fork.
    The DDM attribute DryCavity_CycleSetStaticGuard is a boolean (0/1).
    """

    _attr_options = DRYER_TOGGLE_OPTIONS

    def __init__(self, appliance: Dryer) -> None:
        super().__init__(appliance, "dryer_static_guard", "-static_guard")

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._appliance.get_static_guard_changeable() is True
        )

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_static_guard_str()

    async def async_select_option(self, option: str) -> None:
        if self._appliance.get_static_guard_changeable() is not True:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            )
        self._check(await self._appliance.set_static_guard(option))
        self._invalidate("static_guard", option)


class WhirlpoolDryerEcoBoostSelect(WhirlpoolDryerSelectBase):
    """Eco Boost control for the DDM-proven WED9620HBK2 dryer.

    Implemented as a select (off/on) because no switch.py exists in this fork.
    The DDM attribute DryCavity_CycleSetEcoBoost is a boolean (0/1).
    """

    _attr_options = DRYER_TOGGLE_OPTIONS

    def __init__(self, appliance: Dryer) -> None:
        super().__init__(appliance, "dryer_eco_boost", "-eco_boost")

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._appliance.get_eco_boost_changeable() is True
        )

    @property
    def current_option(self) -> str | None:
        return self._appliance.get_eco_boost_str()

    async def async_select_option(self, option: str) -> None:
        if self._appliance.get_eco_boost_changeable() is not True:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            )
        self._check(await self._appliance.set_eco_boost(option))
        self._invalidate("eco_boost", option)


class WhirlpoolDryerManualDryTimeSelect(WhirlpoolDryerSelectBase):
    """Manual dry time select for the DDM-proven WED9620HBK2 dryer.

    Behaviour is FAIL-CLOSED per cycle group:
      Quick-group cycles   -> options {"15","30","45"}, entity available
      Timed-Dry-group cycles -> options {"30","60","90"}, entity available
      Any other cycle (non-MDT, unknown, or missing CycleSelect)
                           -> entity unavailable, options empty

    The ChangeStatus gate alone is insufficient: live evidence shows
    DryCavity_ChangeStatusManualDryTime="1" while CycleSetCycleSelect="31"
    (TowelsHeavyDuty, a non-MDT cycle).  Cycle-group membership is therefore
    checked independently via Dryer.get_manual_dry_time_options_minutes().

    Wire value: int(option) * 60 seconds.
    """

    def __init__(self, appliance: Dryer) -> None:
        super().__init__(appliance, "dryer_manual_dry_time", "-manual_dry_time")

    @property
    def options(self) -> list[str]:
        """Return allowed MDT options for the current cycle group, or []."""
        opts = self._appliance.get_manual_dry_time_options_minutes()
        return opts if opts is not None else []

    @property
    def available(self) -> bool:
        """Entity is available only when the current cycle supports MDT."""
        return (
            super().available
            and self._appliance.get_manual_dry_time_changeable() is True
            and self._appliance.get_manual_dry_time_options_minutes() is not None
        )

    @property
    def current_option(self) -> str | None:
        """Return current manual dry time as a minutes string, or None."""
        seconds = self._appliance.get_manual_dry_time()
        if seconds is None:
            return None
        minutes = seconds // 60
        key = str(minutes)
        return key if key in DRYER_MANUAL_DRY_TIME_OPTIONS else None

    async def async_select_option(self, option: str) -> None:
        if self._appliance.get_manual_dry_time_changeable() is not True:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            )
        try:
            seconds = int(option) * 60
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            ) from err
        self._check(await self._appliance.set_manual_dry_time(seconds))
        self._invalidate("manual_dry_time", option)


class WhirlpoolDryerFavoriteCycleSelect(FavoriteSelectMixin, WhirlpoolDryerSelectBase):
    """Apply or save a Home Assistant-local dryer Favorite recipe.

    Applying selects the What/How cycle and then writes each recipe setting,
    one attribute per request, as the dryer protocol does. It never sends an
    operation, so it never Starts the dryer. Like every dryer configuration
    control it is gated by the dryer's own changeability, not Remote Enable.
    """

    _kind = "dryer"
    _appliance: Dryer

    def __init__(
        self,
        appliance: Dryer,
        label: CycleLabel | None = None,
        store: favorites.FavoriteStore | None = None,
    ) -> None:
        super().__init__(appliance, "dryer_favorite_cycle", "-favorite_cycle")
        self._init_favorites(label, store)

    @property
    def available(self) -> bool:
        return super().available and self._appliance.get_cycle_changeable() is True

    def _capture(self) -> favorites.DryerFavorite:
        return favorites.capture_dryer_favorite(self._appliance)

    def _label_values(self, recipe: favorites.DryerFavorite) -> dict[str, str | None]:
        # Damp Dry Signal has no HA control, so nothing in HA can change it.
        return {
            field: getattr(recipe, field)
            for field in (
                "temperature",
                "dryness",
                "wrinkle_shield",
                "static_guard",
                "eco_boost",
                "manual_dry_time",
            )
        }

    async def async_select_option(self, option: str) -> None:
        """Apply the selected local recipe without starting the dryer."""
        assert self._label is not None
        if option == "none":
            if self._label.kind == "favorite":
                self._label.clear()
            return

        recipe = self._recipe(option)
        if recipe is None or self._appliance.get_cycle_changeable() is not True:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            )
        try:
            writes_ok = await favorites.apply_dryer_favorite(self._appliance, recipe)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_value_set"
            ) from err
        self._label.clear()  # the cycle selection was attempted
        self._check(writes_ok)
        self._label.apply("favorite", option, self._label_values(recipe))
