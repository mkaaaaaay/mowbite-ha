"""Actions that don't fit the lawn mower entity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import MowbiteConfigEntry
from .const import DOMAIN
from .entity import MowbiteEntity
from .mower import ACTION_RESET_EMERGENCY, ACTION_SKIP_AREA, KEY_ACTIONS, KEY_STATE, CannotConnect
from .snooze import next_morning

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MowbiteButtonDescription(ButtonEntityDescription):
    action_id: str


BUTTONS = (
    MowbiteButtonDescription(key="skip_area", translation_key="skip_area", action_id=ACTION_SKIP_AREA),
    # off until someone turns it on: an emergency stop has a reason out there at the mower, clearing it from afar
    # should be a choice
    MowbiteButtonDescription(
        key="reset_emergency",
        translation_key="reset_emergency",
        action_id=ACTION_RESET_EMERGENCY,
        entity_registry_enabled_default=False,
    ),
)


@dataclass(frozen=True, kw_only=True)
class MowbiteSnoozeButtonDescription(ButtonEntityDescription):
    until_fn: Callable[[], datetime]


SNOOZE_BUTTONS = (
    MowbiteSnoozeButtonDescription(
        key="snooze_hour",
        translation_key="snooze_hour",
        entity_category=EntityCategory.CONFIG,
        until_fn=lambda: dt_util.utcnow() + timedelta(hours=1),
    ),
    MowbiteSnoozeButtonDescription(
        key="snooze_morning",
        translation_key="snooze_morning",
        entity_category=EntityCategory.CONFIG,
        until_fn=next_morning,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MowbiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [
            *(MowbiteButton(entry, description) for description in BUTTONS),
            *(MowbiteSnoozeButton(entry, description) for description in SNOOZE_BUTTONS),
        ]
    )


class MowbiteButton(MowbiteEntity, ButtonEntity):
    """A button for one mower_logic action, only there while the mower takes it."""

    entity_description: MowbiteButtonDescription
    _listen = (KEY_STATE, KEY_ACTIONS)

    def __init__(self, entry: MowbiteConfigEntry, description: MowbiteButtonDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.mower.action_enabled(self.entity_description.action_id) is not False

    async def async_press(self) -> None:
        try:
            await self.mower.async_action(self.entity_description.action_id)
        except CannotConnect as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_connected") from err


class MowbiteSnoozeButton(MowbiteEntity, ButtonEntity):
    """Pauses the notifications for a while."""

    entity_description: MowbiteSnoozeButtonDescription
    _listen = ()

    def __init__(self, entry: MowbiteConfigEntry, description: MowbiteSnoozeButtonDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return True

    async def async_press(self) -> None:
        self.snooze.snooze_until(self.entity_description.until_fn())
