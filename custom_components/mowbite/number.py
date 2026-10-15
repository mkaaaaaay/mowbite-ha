"""Numbers of the planner's settings."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import PERCENTAGE, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MowbiteConfigEntry
from .entity import async_add_when_there
from .features import RPC
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MowbiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_when_there(
        entry,
        async_add_entities,
        [
            (RPC + SETTINGS, lambda description=description: MowbitePlannerNumber(entry, description))
            for description in NUMBERS
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
