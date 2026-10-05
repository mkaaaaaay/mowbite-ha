"""Yes/no from robot_state: emergency, charging, rain."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MowbiteConfigEntry
from .entity import MowbiteEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MowbiteBinarySensorDescription(BinarySensorEntityDescription):
    state_key: str


BINARY_SENSORS = (
    MowbiteBinarySensorDescription(
        key="emergency",
        translation_key="emergency",
        device_class=BinarySensorDeviceClass.PROBLEM,
        state_key="emergency",
    ),
    MowbiteBinarySensorDescription(
        key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        state_key="is_charging",
    ),
    MowbiteBinarySensorDescription(
        key="rain",
        translation_key="rain",
        device_class=BinarySensorDeviceClass.MOISTURE,
        state_key="rain_detected",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MowbiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(MowbiteBinarySensor(entry, description) for description in BINARY_SENSORS)


class MowbiteBinarySensor(MowbiteEntity, BinarySensorEntity):
    """One flag from robot_state."""

    entity_description: MowbiteBinarySensorDescription

    def __init__(self, entry: MowbiteConfigEntry, description: MowbiteBinarySensorDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        if self.mower.state is None:
            return None
        return bool(self.mower.state.get(self.entity_description.state_key))
