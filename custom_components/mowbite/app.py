"""The MowBite app's own settings: the map's colours and symbols as they're set in the app."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

# the app keeps them in its container, the same for every device (docker/settings.cgi)
SETTINGS_PATH = "/cgi-bin/settings"
REFRESH = timedelta(minutes=5)
# what the card uses of them
KEYS = ("colors", "icons", "dashboard")


class CannotReachApp(Exception):
    """No MowBite answers at that address."""


async def async_fetch(hass: HomeAssistant, url: str) -> dict[str, Any]:
    """The app's settings, raises CannotReachApp."""
    try:
        async with async_get_clientsession(hass).get(
            url.rstrip("/") + SETTINGS_PATH, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise CannotReachApp from err
    if not isinstance(data, dict):
        raise CannotReachApp
    return {key: data[key] for key in KEYS if isinstance(data.get(key), dict)}


class AppSettings:
    """The app's settings, read again every few minutes, empty without an address (the card uses the app's defaults)."""

    def __init__(self, hass: HomeAssistant, url: str | None) -> None:
        self._hass = hass
        self._url = url
        self.data: dict[str, Any] = {}
        self.version = 0
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def async_start(self) -> Callable[[], None]:
        """Reads them now and every few minutes, returns how to stop."""
        if not self._url:
            return lambda: None
        await self.async_refresh()
        return async_track_time_interval(self._hass, self._refresh, REFRESH)

    @callback
    def _refresh(self, _now: Any) -> None:
        self._hass.async_create_task(self.async_refresh(), eager_start=True)

    async def async_refresh(self) -> None:
        if not self._url:
            return
        try:
            data = await async_fetch(self._hass, self._url)
        except CannotReachApp:
            _LOGGER.debug("Can't read the MowBite settings at %s", self._url)
            return
        if data != self.data:
            self.data = data
            self.version += 1
            for listener in list(self._listeners):
                listener()
