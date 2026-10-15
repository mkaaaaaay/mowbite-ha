"""What the mower reports: robot_state and the sensors under sensors/<id>/data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    UnitOfArea,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfInformation,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import MowbiteConfigEntry, MowbiteData
from .app import SKIP_REASONS
from .entity import MowbiteEntity, async_add_when_there
from .features import APP, EVENTS, MAP, RPC
from .mower import KEY_STATE, Mower
from .planning import DRIVE, HISTORY, KEY_PLANNING, LEFTOVERS, PLAN, PLANNER_PLAN, mow_areas

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


# what the app's status says, read every minute
KEY_STATUS = "status"


def _round(value: float | None, digits: int = 0) -> float | None:
    if value is None:
        return None
    return round(value, digits) if digits else round(value)


def _timestamp(t: float | None) -> datetime | None:
    return dt_util.utc_from_timestamp(t) if isinstance(t, (int, float)) else None


def _system(key: str, scale: float = 1) -> Callable[[MowbiteData], Any]:
    def value(data: MowbiteData) -> Any:
        number = (data.status.system or {}).get(key)
        return round(number / scale, 1) if isinstance(number, (int, float)) else None

    return value


def _memory_free(data: MowbiteData) -> float | None:
    system = data.status.system or {}
    total, free = system.get("mem_total"), system.get("mem_available")
    if not isinstance(total, (int, float)) or not isinstance(free, (int, float)) or not total:
        return None
    return round(free / total * 100)


def _booted(data: MowbiteData) -> datetime | None:
    uptime = (data.status.system or {}).get("uptime")
    if not isinstance(uptime, (int, float)):
        return None
    # to the minute, otherwise the state changes on every read
    return (dt_util.utcnow() - timedelta(seconds=uptime)).replace(second=0, microsecond=0)


def _leftover_areas(data: MowbiteData) -> dict[str, Any]:
    names = {area.get("id"): (area.get("properties") or {}).get("name") for area in mow_areas(data.mower.map)}
    leftovers = data.planning.leftovers or {"areas": {}}
    areas: dict[str, float] = {}
    for area_id, area in leftovers["areas"].items():
        name = names.get(area_id) or area_id
        # two areas can have the same name
        unique, n = name, 2
        while unique in areas:
            unique, n = f"{name} {n}", n + 1
        areas[unique] = round(area["left_m2"], 1)
    return {"areas": areas}


@dataclass(frozen=True, kw_only=True)
class MowbiteDataSensorDescription(SensorEntityDescription):
    """A value from what's kept next to the mower: its plans, the planner, the app's status."""

    value_fn: Callable[[MowbiteData], Any]
    attributes_fn: Callable[[MowbiteData], dict[str, Any]] | None = None
    # the feature it needs (or any of several), it isn't there before
    feature: str | tuple[str, ...]
    listen: tuple[str, ...] = (KEY_STATE, KEY_PLANNING)
    # the app's values don't need the mower
    needs_mower: bool = True
    min_interval: float = 0


DATA_SENSORS = (
    MowbiteDataSensorDescription(
        key="current_area",
        translation_key="current_area",
        value_fn=lambda data: data.planning.area_name,
        # only the area's leftovers: no progress or time then
        attributes_fn=lambda data: {"leftovers": data.planning.leftover_run},
        feature=(EVENTS, RPC + HISTORY),
    ),
    MowbiteDataSensorDescription(
        key="area_progress",
        translation_key="area_progress",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: _round(None if data.planning.progress is None else data.planning.progress * 100),
        feature=(RPC + PLAN, RPC + PLANNER_PLAN),
        min_interval=10,
    ),
    MowbiteDataSensorDescription(
        key="area_time_left",
        translation_key="area_time_left",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda data: _round(data.planning.area_minutes_left),
        feature=RPC + PLANNER_PLAN,
        min_interval=10,
    ),
    MowbiteDataSensorDescription(
        key="job_time_left",
        translation_key="job_time_left",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda data: _round(data.planning.job_minutes_left),
        feature=RPC + PLANNER_PLAN,
        min_interval=10,
    ),
    MowbiteDataSensorDescription(
        key="job_duration",
        translation_key="job_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda data: _round(data.planning.job_minutes),
        feature=RPC + PLANNER_PLAN,
        listen=(KEY_PLANNING,),
    ),
    MowbiteDataSensorDescription(
        key="lawn_area",
        translation_key="lawn_area",
        device_class=SensorDeviceClass.AREA,
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        suggested_display_precision=0,
        value_fn=lambda data: _round(data.planning.lawn_area, 1),
        feature=MAP,
        listen=(KEY_PLANNING,),
    ),
    MowbiteDataSensorDescription(
        key="leftovers",
        translation_key="leftovers",
        device_class=SensorDeviceClass.AREA,
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        suggested_display_precision=1,
        value_fn=lambda data: _round(data.planning.leftover_m2, 1),
        attributes_fn=_leftover_areas,
        feature=RPC + LEFTOVERS,
        listen=(KEY_PLANNING,),
    ),
    MowbiteDataSensorDescription(
        key="tightest_place",
        translation_key="tightest_place",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        suggested_display_precision=0,
        value_fn=lambda data: _round(None if data.planning.worst_margin is None else data.planning.worst_margin * 100),
        attributes_fn=lambda data: {"places": len(data.planning.card()["tight"])},
        feature=RPC + DRIVE,
        listen=(KEY_PLANNING,),
        entity_registry_enabled_default=False,
    ),
    MowbiteDataSensorDescription(
        key="last_problem",
        translation_key="last_problem",
        value_fn=lambda data: (data.planning.problem or {}).get("message"),
        attributes_fn=lambda data: {
            k: (v.isoformat() if isinstance(v, datetime) else v)
            for k, v in (data.planning.problem or {}).items()
            if k != "message"
        },
        feature=(EVENTS, RPC + HISTORY),
        listen=(KEY_PLANNING,),
    ),
    # from the app
    MowbiteDataSensorDescription(
        key="app_version",
        translation_key="app_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.status.version,
        feature=APP + "version",
        listen=(KEY_STATUS,),
        needs_mower=False,
    ),
    MowbiteDataSensorDescription(
        key="cpu_temperature",
        translation_key="cpu_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_system("cpu_temp"),
        feature=APP + "system",
        listen=(KEY_STATUS,),
        needs_mower=False,
    ),
    MowbiteDataSensorDescription(
        key="memory_free",
        translation_key="memory_free",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_memory_free,
        feature=APP + "system",
        listen=(KEY_STATUS,),
        needs_mower=False,
    ),
    MowbiteDataSensorDescription(
        key="disk_free",
        translation_key="disk_free",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_system("data_free", 1e9),
        feature=APP + "system",
        listen=(KEY_STATUS,),
        needs_mower=False,
    ),
    MowbiteDataSensorDescription(
        key="booted",
        translation_key="booted",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_booted,
        feature=APP + "system",
        listen=(KEY_STATUS,),
        needs_mower=False,
    ),
    MowbiteDataSensorDescription(
        key="schedule_started",
        translation_key="schedule_started",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: _timestamp((data.status.schedule_log or {}).get("started")),
        feature=APP + "schedule_log",
        listen=(KEY_STATUS,),
        needs_mower=False,
    ),
    MowbiteDataSensorDescription(
        key="schedule_skipped",
        translation_key="schedule_skipped",
        device_class=SensorDeviceClass.ENUM,
        options=SKIP_REASONS,
        value_fn=lambda data: (
            reason if (reason := (data.status.schedule_log or {}).get("skip_reason")) in SKIP_REASONS else None
        ),
        attributes_fn=lambda data: {
            "time": t.isoformat() if (t := _timestamp((data.status.schedule_log or {}).get("skipped"))) else None
        },
        feature=APP + "schedule_log",
        listen=(KEY_STATUS,),
        needs_mower=False,
    ),
    MowbiteDataSensorDescription(
        key="blade_time_per_charge",
        translation_key="blade_time_per_charge",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (data.status.battery or {}).get("blade_minutes"),
        attributes_fn=lambda data: {
            "lowest_voltage": (data.status.battery or {}).get("low_voltage"),
            "run_end": t.isoformat() if (t := _timestamp((data.status.battery or {}).get("run_end"))) else None,
        },
        feature=APP + "battery",
        listen=(KEY_STATUS,),
        needs_mower=False,
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
    async_add_when_there(
        entry,
        async_add_entities,
        [
            (description.feature, lambda description=description: MowbiteDataSensor(entry, description))
            for description in DATA_SENSORS
        ],
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


class MowbiteDataSensor(MowbiteEntity, SensorEntity):
    """A value from the mower's plans, its planner or the app."""

    entity_description: MowbiteDataSensorDescription

    def __init__(self, entry: MowbiteConfigEntry, description: MowbiteDataSensorDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description
        self._data: MowbiteData = entry.runtime_data
        self._listen = description.listen
        self._written_at = 0.0
        self._written: tuple[Any, bool, dict[str, Any] | None] | None = None

    @property
    def available(self) -> bool:
        if not self.entity_description.needs_mower:
            # the computer's values go with it, the others are what it said last
            return self.entity_description.feature != APP + "system" or self._data.status.system is not None
        return super().available

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self._data)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if KEY_STATUS in self._listen:
            self.async_on_remove(self._data.status.add_listener(self._update))

    @callback
    def _update(self) -> None:
        now = time.monotonic()
        written = (self.native_value, self.available, self.extra_state_attributes)
        if written == self._written:
            return
        # a value that only moves on is written every so often, one that comes, goes or gets unavailable right away
        if (
            self._written is not None
            and self._written[1] == written[1]
            and None not in (self._written[0], written[0])
            and now - self._written_at < self.entity_description.min_interval
        ):
            return
        self._written_at = now
        self._written = written
        self.async_write_ha_state()
