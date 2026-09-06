"""Binary sensors for the Whirlpool Appliances integration.

Modified from upstream to add a read-only Remote Control Enable status
sensor for washers/dryers (see WASHER_DRYER_SENSORS below). This sensor
has no corresponding way to turn Remote Control on or off from Home
Assistant - see CHANGES.md in this fork for why."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import override

from whirlpool.appliance import Appliance

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WhirlpoolConfigEntry
from .entity import WhirlpoolEntity

PARALLEL_UPDATES = 1
SCAN_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True, kw_only=True)
class WhirlpoolBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Whirlpool binary sensor entity."""

    value_fn: Callable[[Appliance], bool | None]


WASHER_DRYER_SENSORS: list[WhirlpoolBinarySensorEntityDescription] = [
    WhirlpoolBinarySensorEntityDescription(
        key="door",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda appliance: appliance.get_door_open(),
    ),
    WhirlpoolBinarySensorEntityDescription(
        key="remote_control_enabled",
        translation_key="remote_control_enabled",
        value_fn=lambda appliance: appliance.get_remote_control_enabled(),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: WhirlpoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Config flow entry for Whirlpool binary sensors."""
    appliances_manager = config_entry.runtime_data

    washer_binary_sensors = [
        WhirlpoolBinarySensor(washer, description)
        for washer in appliances_manager.washers
        for description in WASHER_DRYER_SENSORS
    ]

    dryer_binary_sensors = [
        WhirlpoolBinarySensor(dryer, description)
        for dryer in appliances_manager.dryers
        for description in WASHER_DRYER_SENSORS
    ]

    async_add_entities([*washer_binary_sensors, *dryer_binary_sensors])


class WhirlpoolBinarySensor(WhirlpoolEntity, BinarySensorEntity):
    """A class for the Whirlpool binary sensors."""

    def __init__(
        self, appliance: Appliance, description: WhirlpoolBinarySensorEntityDescription
    ) -> None:
        """Initialize the washer sensor."""
        super().__init__(appliance, unique_id_suffix=f"-{description.key}")
        self.entity_description: WhirlpoolBinarySensorEntityDescription = description

    @property
    @override
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        return self.entity_description.value_fn(self._appliance)
