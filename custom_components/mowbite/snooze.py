"""Pausing the mower's notifications, for a while or until they're switched on again."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

STORAGE_VERSION = 1
# "until tomorrow morning" ends the next time it's this late
MORNING_HOUR = 7

# what the buttons in a notification send back (mobile_app_notification_action), followed by the entry id
ACTION_SNOOZE_HOUR = "MOWBITE_SNOOZE_HOUR_"
ACTION_SNOOZE_MORNING = "MOWBITE_SNOOZE_MORNING_"


def next_morning(now: datetime | None = None) -> datetime:
    now = now or dt_util.now()
    morning = now.replace(hour=MORNING_HOUR, minute=0, second=0, microsecond=0)
    return morning if morning > now else morning + timedelta(days=1)


class Snooze:
    """Whether notifications go out, shared by the switch, the sensor, the buttons and the event entity."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"mowbite.{entry_id}.snooze")
        # switched off until someone switches it on again
        self.off = False
        # paused until then
        self.until: datetime | None = None
        self._timer: CALLBACK_TYPE | None = None
        self._listeners: list[Callable[[], None]] = []

    @property
    def active(self) -> bool:
        """Whether notifications go out right now."""
        return not self.off and self.until is None

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.off = bool(data.get("off"))
        until = dt_util.parse_datetime(data["until"]) if data.get("until") else None
        if until is not None and until > dt_util.utcnow():
            self._set_until(until)

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def snooze_until(self, until: datetime) -> None:
        self.off = False
        self._set_until(until)
        self._changed()

    @callback
    def turn_on(self) -> None:
        self.off = False
        self._set_until(None)
        self._changed()

    @callback
    def turn_off(self) -> None:
        self.off = True
        self._set_until(None)
        self._changed()

    @callback
    def unload(self) -> None:
        if self._timer:
            self._timer()
            self._timer = None

    def _set_until(self, until: datetime | None) -> None:
        self.unload()
        self.until = until
        if until is not None:
            self._timer = async_track_point_in_utc_time(self._hass, self._ended, until)

    @callback
    def _ended(self, _now: datetime) -> None:
        self._timer = None
        self.until = None
        self._changed()

    def _changed(self) -> None:
        self._store.async_delay_save(
            lambda: {"off": self.off, "until": self.until.isoformat() if self.until else None}, 1
        )
        for listener in list(self._listeners):
            listener()
