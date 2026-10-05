"""Notifications on or off."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MowbiteConfigEntry
from .entity import MowbiteEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MowbiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([MowbiteNotificationsSwitch(entry)])


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
