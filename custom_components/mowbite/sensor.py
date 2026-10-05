"""What the mower reports: robot_state and the sensors under sensors/<id>/data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import time
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MowbiteConfigEntry
from .entity import MowbiteEntity
from .mower import KEY_STATE, Mower

PARALLEL_UPDATES = 0

STATES = ["idle", "mowing", "docking", "undocking", "paused", "area_recording"]


def _percent(key: str) -> Callable[[Mower], Any]:
    def value(mower: Mower) -> Any:
        number = (mower.state or {}).get(key)
        return round(number * 100) if isinstance(number, (int, float)) else None

    return value


def _state(mower: Mower) -> str | None:
    state = str((mower.state or {}).get("current_state", "")).lower()
    return state if state in STATES else None


def _accuracy(mower: Mower) -> float | None:
    accuracy = ((mower.state or {}).get("pose") or {}).get("pos_accuracy")
    return round(accuracy, 3) if isinstance(accuracy, (int, float)) else None


@dataclass(frozen=True, kw_only=True)
class MowbiteSensorDescription(SensorEntityDescription):
    # from robot_state when set, otherwise the sensor topic named by sensor_id
    value_fn: Callable[[Mower], Any] | None = None
    sensor_id: str | None = None
    # these come about once a second, a value every few seconds is plenty for a history
    min_interval: float = 0


STATE_SENSORS = (
    MowbiteSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_percent("battery_percentage"),
    ),
    MowbiteSensorDescription(
        key="state",
        translation_key="state",
        device_class=SensorDeviceClass.ENUM,
        options=STATES,
        value_fn=_state,
    ),
    MowbiteSensorDescription(
        key="gps_quality",
        translation_key="gps_quality",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_percent("gps_percentage"),
        min_interval=10,
    ),
    MowbiteSensorDescription(
        key="position_accuracy",
        translation_key="position_accuracy",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_accuracy,
        min_interval=10,
    ),
)


def _temperature(key: str, sensor_id: str, enabled: bool = False) -> MowbiteSensorDescription:
    return MowbiteSensorDescription(
        key=key,
        translation_key=key,
        sensor_id=sensor_id,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=None if enabled else EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=enabled,
        min_interval=10,
    )


TOPIC_SENSORS = (
    MowbiteSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        sensor_id="om_v_battery",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        min_interval=10,
    ),
    MowbiteSensorDescription(
        key="charge_voltage",
        translation_key="charge_voltage",
        sensor_id="om_v_charge",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        min_interval=10,
    ),
    MowbiteSensorDescription(
        key="charge_current",
        translation_key="charge_current",
        sensor_id="om_charge_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        min_interval=10,
    ),
    _temperature("mow_motor_temperature", "om_mow_motor_temp", enabled=True),
    _temperature("mow_esc_temperature", "om_mow_esc_temp"),
    _temperature("left_esc_temperature", "om_left_esc_temp"),
    _temperature("right_esc_temperature", "om_right_esc_temp"),
    MowbiteSensorDescription(
        key="mow_motor_current",
        translation_key="mow_motor_current",
        sensor_id="om_mow_motor_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        min_interval=10,
    ),
    # turns either way when the mower randomizes the direction, the speed is what's interesting
    MowbiteSensorDescription(
        key="mow_motor_speed",
        translation_key="mow_motor_speed",
        sensor_id="om_mow_motor_rpm",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        min_interval=10,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MowbiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [
            *(MowbiteSensor(entry, description) for description in (*STATE_SENSORS, *TOPIC_SENSORS)),
            MowbiteSnoozeSensor(entry),
        ]
    )


class MowbiteSensor(MowbiteEntity, SensorEntity):
    """One value from the mower."""

    entity_description: MowbiteSensorDescription

    def __init__(self, entry: MowbiteConfigEntry, description: MowbiteSensorDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description
        if description.sensor_id:
            self._listen = (f"sensor:{description.sensor_id}",)
        else:
            self._listen = (KEY_STATE,)
        self._written_at = 0.0
        self._written_available: bool | None = None

    @property
    def available(self) -> bool:
        sensor_id = self.entity_description.sensor_id
        return super().available and (sensor_id is None or sensor_id in self.mower.sensors)

    @property
    def native_value(self) -> Any:
        description = self.entity_description
        if description.value_fn:
            return description.value_fn(self.mower)
        value = self.mower.sensors.get(description.sensor_id or "")
        if not isinstance(value, float):
            return None
        return abs(value) if description.key == "mow_motor_speed" else value

    @callback
    def _update(self) -> None:
        now = time.monotonic()
        available = self.available
        if available == self._written_available and now - self._written_at < self.entity_description.min_interval:
            return
        self._written_at = now
        self._written_available = available
        self.async_write_ha_state()


class MowbiteSnoozeSensor(MowbiteEntity, SensorEntity):
    """When paused notifications go out again, empty while they aren't paused for a while."""

    _attr_translation_key = "notifications_paused_until"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _listen = ()

    def __init__(self, entry: MowbiteConfigEntry) -> None:
        super().__init__(entry, "notifications_paused_until")

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> datetime | None:
        return self.snooze.until

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.snooze.add_listener(self.async_write_ha_state))
