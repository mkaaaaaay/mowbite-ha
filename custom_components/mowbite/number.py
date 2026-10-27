"""Numbers of the planner's settings."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MowbiteConfigEntry
from .app import AppRefused, AppStatus
from .const import DOMAIN
from .entity import MowbiteEntity, async_add_when_there
from .features import APP, RPC
from .planner_setting import MowbitePlannerSetting
from .planning import SETTINGS

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MowbitePlannerNumberDescription(NumberEntityDescription):
    # shown as the planner's value times this (0.33 overlap as 33 %)
    scale: float = 1
    integer: bool = False


NUMBERS = (
    # -1 lets the planner choose
    MowbitePlannerNumberDescription(
        key="perimeter_passes", native_min_value=-1, native_max_value=10, native_step=1, integer=True
    ),
    MowbitePlannerNumberDescription(
        key="obstacle_passes",
        native_min_value=-1,
        native_max_value=10,
        native_step=1,
        integer=True,
        entity_registry_enabled_default=False,
    ),
    MowbitePlannerNumberDescription(
        key="overlap",
        native_min_value=0,
        native_max_value=90,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        scale=100,
        entity_registry_enabled_default=False,
    ),
    MowbitePlannerNumberDescription(
        key="turn_radius",
        native_min_value=0,
        native_max_value=2,
        native_step=0.01,
        native_unit_of_measurement=UnitOfLength.METERS,
        entity_registry_enabled_default=False,
    ),
)


@dataclass(frozen=True, kw_only=True)
class MowbiteAppNumberDescription(NumberEntityDescription):
    """A number set in the MowBite app, off at first like everything that changes something there."""

    value_fn: Callable[[AppStatus], float | None]
    set_fn: Callable[[AppStatus, int], Awaitable[None]]
    feature: str
    entity_registry_enabled_default: bool = False
    entity_category: EntityCategory | None = EntityCategory.CONFIG
    mode: NumberMode = NumberMode.BOX


def _due_hours(part: str) -> Callable[[AppStatus], float | None]:
    def value(status: AppStatus) -> float | None:
        hours = ((status.stats or {}).get("parts", {}).get(part) or {}).get("due_hours")
        return None if hours is None else int(hours)

    return value


APP_NUMBERS = (
    # after how many blade hours the part is due again, as the app keeps it (1 to 5000)
    MowbiteAppNumberDescription(
        key="blade_interval",
        translation_key="blade_interval",
        native_min_value=1,
        native_max_value=5000,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        value_fn=_due_hours("blade"),
        set_fn=lambda status, hours: status.async_part_due("blade", hours),
        feature=APP + "maint_blade",
    ),
    MowbiteAppNumberDescription(
        key="cleaning_interval",
        translation_key="cleaning_interval",
        native_min_value=1,
        native_max_value=5000,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        value_fn=_due_hours("clean"),
        set_fn=lambda status, hours: status.async_part_due("clean", hours),
        feature=APP + "maint_clean",
    ),
    # the schedule doesn't start below it
    MowbiteAppNumberDescription(
        key="min_battery",
        translation_key="min_battery",
        native_min_value=0,
        native_max_value=100,
        native_step=5,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda status: (status.schedule or {}).get("minbattery"),
        set_fn=lambda status, value: status.async_schedule_set({"minbattery": str(value)}),
        feature=APP + "schedule",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MowbiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_when_there(
        entry,
        async_add_entities,
        [
            *(
                (RPC + SETTINGS, lambda description=description: MowbitePlannerNumber(entry, description))
                for description in NUMBERS
            ),
            *(
                (description.feature, lambda description=description: MowbiteAppNumber(entry, description))
                for description in APP_NUMBERS
            ),
        ],
    )


class MowbitePlannerNumber(MowbitePlannerSetting, NumberEntity):
    entity_description: MowbitePlannerNumberDescription
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: MowbiteConfigEntry, description: MowbitePlannerNumberDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description
        self._attr_translation_key = f"planner_{description.key}"

    @property
    def native_value(self) -> float | None:
        value = self.setting_value
        if not isinstance(value, (int, float)):
            return None
        return round(value * self.entity_description.scale, 3)

    async def async_set_native_value(self, value: float) -> None:
        value /= self.entity_description.scale
        await self.async_set_setting(round(value) if self.entity_description.integer else round(value, 4))


class MowbiteAppNumber(MowbiteEntity, NumberEntity):
    """A number set in the MowBite app, without the mower."""

    entity_description: MowbiteAppNumberDescription
    _listen = ()

    def __init__(self, entry: MowbiteConfigEntry, description: MowbiteAppNumberDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description
        self._attr_mode = description.mode
        self._status = entry.runtime_data.status

    @property
    def available(self) -> bool:
        return self.native_value is not None

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value_fn(self._status)

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.entity_description.set_fn(self._status, round(value))
        except AppRefused as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="app_refused") from err

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._status.add_listener(self.async_write_ha_state))
