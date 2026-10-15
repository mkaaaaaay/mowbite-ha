"""Choices of the planner's settings."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MowbiteConfigEntry
from .entity import async_add_when_there
from .features import RPC
from .planner_setting import MowbitePlannerSetting
from .planning import SETTINGS

PARALLEL_UPDATES = 0

# the setting and its choices as the planner has them, and whether it's on from the start
SELECTS = {
    "fill_pattern": (["lanes", "crosshatch", "concentric"], True),
    "angle_strategy": (["longest_edge", "min_width", "optimal"], False),
    "lane_order": (["snake", "skip"], False),
    "route_order": (["nearest", "optimized"], False),
    "perimeter_order": (["first", "last"], False),
    "perimeter_direction": (["auto", "ccw", "cw"], False),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MowbiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_when_there(
        entry,
        async_add_entities,
        [(RPC + SETTINGS, lambda setting=setting: MowbitePlannerSelect(entry, setting)) for setting in SELECTS],
    )


class MowbitePlannerSelect(MowbitePlannerSetting, SelectEntity):
    def __init__(self, entry: MowbiteConfigEntry, setting: str) -> None:
        super().__init__(entry, setting)
        self._attr_translation_key = f"planner_{setting}"
        self._attr_options, self._attr_entity_registry_enabled_default = SELECTS[setting]

    @property
    def current_option(self) -> str | None:
        value = self.setting_value
        return value if value in self.options else None

    async def async_select_option(self, option: str) -> None:
        await self.async_set_setting(option)
