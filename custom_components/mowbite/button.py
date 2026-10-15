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
from .entity import MowbiteEntity, async_add_when_there
from .features import ACTION, RPC
from .mower import (
    ACTION_RESET_EMERGENCY,
    ACTION_RESET_JOB,
    ACTION_SKIP_AREA,
    ACTION_SKIP_PATH,
    ACTION_START,
    KEY_ACTIONS,
    KEY_STATE,
    CannotConnect,
    RpcError,
)
from .planning import ANGLE_RESET, KEY_PLANNING, LEFTOVERS
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


# only on mowers whose OpenMower has them
NEWER_BUTTONS = (
    MowbiteButtonDescription(key="skip_path", translation_key="skip_path", action_id=ACTION_SKIP_PATH),
    MowbiteButtonDescription(key="reset_job", translation_key="reset_job", action_id=ACTION_RESET_JOB),
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
    async_add_when_there(
        entry,
        async_add_entities,
        [
            *(
                (ACTION + description.action_id, lambda description=description: MowbiteButton(entry, description))
                for description in NEWER_BUTTONS
            ),
            (RPC + LEFTOVERS, lambda: MowbiteLeftoversButton(entry)),
            (RPC + ANGLE_RESET, lambda: MowbiteAngleResetButton(entry)),
        ],
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


class MowbiteLeftoversButton(MowbiteEntity, ButtonEntity):
    """Mows what the last job left: the planner gets the leftovers ready, then the mower starts. Only there while
    the mower is idle and there are leftovers to mow"""

    _attr_translation_key = "mow_leftovers"
    _listen = (KEY_STATE, KEY_ACTIONS, KEY_PLANNING)

    def __init__(self, entry: MowbiteConfigEntry) -> None:
        super().__init__(entry, "mow_leftovers")
        self._planning = entry.runtime_data.planning

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.mower.action_enabled(ACTION_START) is True
            and bool(self._planning.leftover_paths)
        )

    async def async_press(self) -> None:
        try:
            await self._planning.async_arm_leftovers()
            await self.mower.async_action(ACTION_START)
        except CannotConnect as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_connected") from err
        except (RpcError, TimeoutError) as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="planner_failed") from err


class MowbiteAngleResetButton(MowbiteEntity, ButtonEntity):
    """The planner turns the lanes a little each mow (angle increment), this starts it again at its first angle."""

    _attr_translation_key = "reset_angle"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: MowbiteConfigEntry) -> None:
        super().__init__(entry, "reset_angle")
        self._planning = entry.runtime_data.planning

    async def async_press(self) -> None:
        if (self.mower.state or {}).get("current_state") not in (None, "IDLE"):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="only_idle")
        try:
            await self._planning.async_reset_angle()
        except CannotConnect as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_connected") from err
        except (RpcError, TimeoutError) as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="planner_failed") from err
