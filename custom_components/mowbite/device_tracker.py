"""Where the mower is, as a gps tracker: for zones in automations ("the mower entered the front garden")."""

from __future__ import annotations

import math
import time
from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import MowbiteConfigEntry
from .entity import MowbiteEntity, async_add_when_there
from .features import DATUM
from .geo import map_to_latlon
from .mower import KEY_POSITION, KEY_STATE

PARALLEL_UPDATES = 0

# the position comes several times a second while driving: written when it moved this far (m) and this long (s) after
# the last time, so zones still notice it soon and the history doesn't fill up
MIN_MOVE = 0.5
MIN_INTERVAL = 10


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MowbiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    # only once the mower told its gps datum: without it its map has no place on earth
    async_add_when_there(entry, async_add_entities, [(DATUM, lambda: MowbiteTracker(entry))])


class MowbiteTracker(MowbiteEntity, TrackerEntity):
    """The mower's position on earth, from its map position and the gps datum."""

    _attr_name = None
    _attr_translation_key = "position"
    _listen = (KEY_POSITION, KEY_STATE)

    def __init__(self, entry: MowbiteConfigEntry) -> None:
        super().__init__(entry, "position")
        # where it is on its map and how exactly (m)
        self._here: tuple[float, float, float] | None = None
        self._written: tuple[float, float] | None = None
        self._written_at = 0.0
        self._written_available: bool | None = None
        self._later: CALLBACK_TYPE | None = None

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def available(self) -> bool:
        return super().available and self.mower.datum is not None and self._here is not None

    def _where(self) -> tuple[float, float, float] | None:
        """Where it is on its map (position/json while it comes, else robot_state's pose) and how exactly. Without a
        gps fix where it last had one: the pose then is only a guess from the wheels, it shouldn't move it in a zone"""
        pose = self.mower.position or (self.mower.state or {}).get("pose")
        if not isinstance(pose, dict) or not isinstance(pose.get("x"), (int, float)):
            return None
        accuracy = ((self.mower.state or {}).get("pose") or {}).get("pos_accuracy")
        if not isinstance(accuracy, (int, float)):
            accuracy = 0
        # 999 and more is no fix at all
        elif accuracy >= 999:
            return self._here
        return float(pose["x"]), float(pose.get("y") or 0), round(accuracy, 2)

    @property
    def latitude(self) -> float | None:
        here, datum = self._here, self.mower.datum
        return map_to_latlon(datum, here[0], here[1])[0] if here and datum else None

    @property
    def longitude(self) -> float | None:
        here, datum = self._here, self.mower.datum
        return map_to_latlon(datum, here[0], here[1])[1] if here and datum else None

    @property
    def location_accuracy(self) -> float:
        return self._here[2] if self._here else 0

    async def async_added_to_hass(self) -> None:
        self._here = self._where()
        await super().async_added_to_hass()

    async def async_will_remove_from_hass(self) -> None:
        if self._later:
            self._later()
        await super().async_will_remove_from_hass()

    @callback
    def _update(self) -> None:
        self._here = self._where()
        available = self.available
        point = self._here[:2] if self._here else None
        now = time.monotonic()
        if available == self._written_available and point and self._written:
            if math.dist(point, self._written) < MIN_MOVE:
                return
            wait = MIN_INTERVAL - (now - self._written_at)
            if wait > 0:
                # moved, but written a moment ago: once the time is up, where it is then (also when it stopped)
                if self._later is None:
                    self._later = async_call_later(self.hass, wait, self._write_later)
                return
        self._write(available, point, now)

    @callback
    def _write_later(self, _now: Any) -> None:
        self._later = None
        self._write(self.available, self._here[:2] if self._here else None, time.monotonic())

    @callback
    def _write(self, available: bool, point: tuple[float, float] | None, now: float) -> None:
        self._written_available = available
        self._written = point
        self._written_at = now
        self.async_write_ha_state()
