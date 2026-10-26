"""The app's schedule as a calendar: when it starts the mower, read only (the app is where it's set), off at first."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import MowbiteConfigEntry
from .app import schedule_starts
from .entity import MowbiteEntity, async_add_when_there
from .features import APP

PARALLEL_UPDATES = 0

# a start without an end time in its plan is shown this long
NO_END = timedelta(hours=1)
SUMMARY = {"de": "Mähen", "en": "Mowing"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MowbiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_when_there(entry, async_add_entities, [(APP + "schedule", lambda: MowbiteScheduleCalendar(entry))])


class MowbiteScheduleCalendar(MowbiteEntity, CalendarEntity):
    """The schedule's starts, the plans' end times or an hour, whole days paused left out."""

    _attr_translation_key = "schedule"
    _attr_entity_registry_enabled_default = False
    _listen = ()

    def __init__(self, entry: MowbiteConfigEntry) -> None:
        super().__init__(entry, "schedule_calendar")
        self._status = entry.runtime_data.status

    @property
    def available(self) -> bool:
        return self._status.schedule is not None

    def _events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        lang = (self.hass.config.language or "en").split("-")[0].lower()
        names = {
            area.get("id"): (area.get("properties") or {}).get("name")
            for area in (self.mower.map or {}).get("areas") or []
            if isinstance(area, dict)
        }
        events = []
        for run in schedule_starts(self._status.schedule, start, end):
            areas = ", ".join(names.get(a) or a for a in run["areas"])
            events.append(
                CalendarEvent(
                    start=run["start"],
                    end=run["end"] or run["start"] + NO_END,
                    summary=SUMMARY.get(lang, SUMMARY["en"]),
                    description=areas or None,
                )
            )
        return events

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = [e for e in self._events(now - NO_END, now + timedelta(days=8)) if e.end > now]
        return upcoming[0] if upcoming else None

    async def async_get_events(self, hass: HomeAssistant, start_date: datetime, end_date: datetime) -> list[CalendarEvent]:
        return self._events(dt_util.as_local(start_date), dt_util.as_local(end_date))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._status.add_listener(self.async_write_ha_state))
