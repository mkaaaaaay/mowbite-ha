"""What the mower and the app can do, so an entity only comes once there's something behind it."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1

# what a feature is called: an rpc the mower answers, an action it lists, an endpoint of the app
RPC = "rpc:"
ACTION = "action:"
APP = "app:"
# events/json came (any OpenMower that records events)
EVENTS = "events"
# map/json came with an area to mow
MAP = "map"
# the gps datum came (params/json): the map has a place on earth
DATUM = "datum"


class Features:
    """The features seen so far, kept over restarts: a mower that's off in winter keeps its entities."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[list[str]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.features")
        self._have: set[str] = set()
        self._listeners: list[Callable[[], None]] = []

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if isinstance(stored, list):
            self._have = {feature for feature in stored if isinstance(feature, str)}

    def has(self, need: str | Iterable[str]) -> bool:
        """One feature, or any of several."""
        if isinstance(need, str):
            return need in self._have
        return any(feature in self._have for feature in need)

    @callback
    def add(self, features: Iterable[str]) -> None:
        new = set(features) - self._have
        if not new:
            return
        self._have |= new
        self._store.async_delay_save(lambda: sorted(self._have), 5)
        for listener in list(self._listeners):
            listener()

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def async_remove(self) -> None:
        await self._store.async_remove()
