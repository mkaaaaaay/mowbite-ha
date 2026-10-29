"""Notifications on or off, and the planner's on/off settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MowbiteConfigEntry
from .app import AppRefused
from .const import DOMAIN
from .entity import MowbiteEntity, async_add_when_there
from .features import APP, RPC
from .planner_setting import MowbitePlannerSetting
from .planning import SETTINGS

PARALLEL_UPDATES = 0

# the planner's settings, and whether each is on from the start. leftovers_auto sends the mower out again by itself
# after a job for what it left
PLANNER_SWITCHES = {"leftovers_auto": True, "mop_up": False, "body_fit": False}


@dataclass(frozen=True, kw_only=True)
class MowbiteScheduleSwitchDescription(SwitchEntityDescription):
    """One of the app's schedule's on/off lines, off at first like everything that changes something there."""

    line: str
    entity_registry_enabled_default: bool = False


SCHEDULE_SWITCHES = (
    MowbiteScheduleSwitchDescription(key="schedule_enabled", translation_key="schedule_enabled", line="enabled"),
    MowbiteScheduleSwitchDescription(
        key="skip_rain", translation_key="skip_rain", line="skiprain", entity_category=EntityCategory.CONFIG
    ),
    MowbiteScheduleSwitchDescription(
        key="skip_forecast", translation_key="skip_forecast", line="skipforecast", entity_category=EntityCategory.CONFIG
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MowbiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([MowbiteNotificationsSwitch(entry)])
    async_add_when_there(
        entry,
        async_add_entities,
        [
            *(
                (RPC + SETTINGS, lambda setting=setting: MowbitePlannerSwitch(entry, setting))
                for setting in PLANNER_SWITCHES
            ),
            *(
                (APP + "schedule", lambda description=description: MowbiteScheduleSwitch(entry, description))
                for description in SCHEDULE_SWITCHES
            ),
        ],
    )


class MowbiteNotificationsSwitch(MowbiteEntity, SwitchEntity):
    """Off while notifications are paused, for a while (snoozed) or until switched on again."""

    _attr_translation_key = "notifications"
    _attr_entity_category = EntityCategory.CONFIG
    _listen = ()

    def __init__(self, entry: MowbiteConfigEntry) -> None:
        super().__init__(entry, "notifications")

    @property
    def available(self) -> bool:
        # a setting here in Home Assistant, the mower doesn't have to be there for it
        return True

    @property
    def is_on(self) -> bool:
        return self.snooze.active

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.snooze.add_listener(self.async_write_ha_state))

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.snooze.turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.snooze.turn_off()


class MowbitePlannerSwitch(MowbitePlannerSetting, SwitchEntity):
    def __init__(self, entry: MowbiteConfigEntry, setting: str) -> None:
        super().__init__(entry, setting)
        self._attr_translation_key = f"planner_{setting}"
        self._attr_entity_registry_enabled_default = PLANNER_SWITCHES[setting]

    @property
    def is_on(self) -> bool | None:
        value = self.setting_value
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.async_set_setting(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_set_setting(False)


class MowbiteScheduleSwitch(MowbiteEntity, SwitchEntity):
    """A line of the app's schedule switched from here, the rest of the schedule stays as it is."""

    entity_description: MowbiteScheduleSwitchDescription
    _listen = ()

    def __init__(self, entry: MowbiteConfigEntry, description: MowbiteScheduleSwitchDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description
        self._status = entry.runtime_data.status

    @property
    def available(self) -> bool:
        return (self._status.schedule or {}).get(self.entity_description.line) is not None

    @property
    def is_on(self) -> bool | None:
        return (self._status.schedule or {}).get(self.entity_description.line)

    async def _set(self, on: bool) -> None:
        try:
            await self._status.async_schedule_set({self.entity_description.line: "1" if on else "0"})
        except AppRefused as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="app_refused") from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._status.add_listener(self.async_write_ha_state))
