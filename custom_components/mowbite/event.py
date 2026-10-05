"""The mower's events: what automations and notifications start from."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import MowbiteConfigEntry
from .entity import MowbiteEntity
from .events import EVENT_TYPES, EventReader, Texts
from .snooze import ACTION_SNOOZE_HOUR, ACTION_SNOOZE_MORNING

PARALLEL_UPDATES = 0

# events held back for a few seconds, to see what follows them (the same as the MowBite app's notifications):
# - sending the mower home while it mows makes mower_logic publish NAVIGATION_ERROR right before STATE DOCKING
#   (MowingBehavior only leaves it out for a pause, not for an abort), a real one isn't followed by the way home
# - a mow motor that doesn't start puts the mower into an emergency stop right after, that's one message: the
#   emergency stop with the motor as its reason
# - an emergency stop counts once it holds this long, one that's gone again before (a bump while leaving the dock)
#   is no message at all, and no "cleared" either
HOLD = {"navigation_error": 3, "mow_motor_spinup_failed": 15, "emergency": 10}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MowbiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([MowbiteEvent(entry)])


class MowbiteEvent(MowbiteEntity, EventEntity):
    """Fires once for each of the mower's events: what OpenMower sends on events/json, and emergency stops."""

    _attr_translation_key = "events"
    _attr_event_types = EVENT_TYPES

    def __init__(self, entry: MowbiteConfigEntry) -> None:
        super().__init__(entry, "events")
        self._entry_id = entry.entry_id
        self._reader = EventReader()
        self._held: dict[str, CALLBACK_TYPE] = {}

    @property
    def available(self) -> bool:
        # events can come before the first robot_state (BOOTED right after connecting), they'd be lost otherwise
        return self.mower.connected

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.mower.add_event_listener(self._event))
        self.async_on_remove(self._drop_all)

    @callback
    def _event(self, event: dict[str, Any]) -> None:
        if event.get("type") == "STATE" and event.get("state") == "DOCKING":
            self._drop("navigation_error")
        # the message in the language Home Assistant is set to, for notifications that just pass it on
        texts = Texts(self.hass.config.language)
        fallback = (self.mower.state or {}).get("current_state")
        fired = self._reader.read(event, texts, fallback)
        if fired is None:
            return
        event_type, attributes = fired
        if event_type == "emergency" and "mow_motor_spinup_failed" in self._held:
            self._drop("mow_motor_spinup_failed")
            attributes.update(reason="mow_motor_spinup_failed", message=texts("emergency_spinup"))
        if event_type == "emergency_cleared" and "emergency" in self._held:
            self._drop("emergency")
            return
        # whether notifications are paused, and the buttons a notification can offer to pause them (the app
        # fires mobile_app_notification_action with that action when one is pressed)
        attributes["snoozed"] = not self.snooze.active
        attributes["notification_actions"] = [
            {"action": ACTION_SNOOZE_HOUR + self._entry_id, "title": texts("snooze_hour")},
            {"action": ACTION_SNOOZE_MORNING + self._entry_id, "title": texts("snooze_morning")},
        ]
        if event_type in HOLD:
            self._hold(event_type, attributes)
        else:
            self._fire(event_type, attributes)

    @callback
    def _hold(self, event_type: str, attributes: dict[str, Any]) -> None:
        self._drop(event_type)

        @callback
        def fire(_now: Any) -> None:
            self._held.pop(event_type, None)
            self._fire(event_type, attributes)

        self._held[event_type] = async_call_later(self.hass, HOLD[event_type], fire)

    @callback
    def _drop(self, event_type: str) -> None:
        if cancel := self._held.pop(event_type, None):
            cancel()

    @callback
    def _drop_all(self) -> None:
        for event_type in list(self._held):
            self._drop(event_type)

    @callback
    def _fire(self, event_type: str, attributes: dict[str, Any]) -> None:
        self._trigger_event(event_type, attributes)
        self.async_write_ha_state()
