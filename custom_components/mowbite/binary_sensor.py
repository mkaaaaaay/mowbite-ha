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
from .entity import MowbiteEntity, async_add_when_there
from .features import APP

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
    async_add_when_there(entry, async_add_entities, [(APP + "schedule", lambda: MowbiteScheduleSensor(entry))])


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


class MowbiteScheduleSensor(MowbiteEntity, BinarySensorEntity):
    """Whether the app's schedule starts the mower, as the app has it (read only, the app is where it's set)."""

    _attr_translation_key = "schedule"
    _listen = ()

    def __init__(self, entry: MowbiteConfigEntry) -> None:
        super().__init__(entry, "schedule")
        self._status = entry.runtime_data.status

    @property
    def available(self) -> bool:
        return self._status.schedule is not None

    @property
    def is_on(self) -> bool | None:
        return None if self._status.schedule is None else self._status.schedule["enabled"]

    @property
    def extra_state_attributes(self) -> dict[str, int] | None:
        return None if self._status.schedule is None else {"plans": self._status.schedule["plans"]}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._status.add_listener(self.async_write_ha_state))
