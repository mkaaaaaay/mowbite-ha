"""MowBite: an OpenMower in Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from . import websocket
from .app import AppSettings
from .const import CONF_APP_URL, CONF_MAP, CONF_PREFIX, DOMAIN
from .mower import Mower
from .snooze import ACTION_SNOOZE_HOUR, ACTION_SNOOZE_MORNING, Snooze, next_morning

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.LAWN_MOWER,
    Platform.SENSOR,
    Platform.SWITCH,
]

# what the Home Assistant app fires when a button in a notification is pressed
EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# the card comes with the integration, every dashboard can use it without adding it as a resource
CARD_URL = "/mowbite"
CARD_FILE = Path(__file__).parent / "frontend" / "mowbite-card.js"
CARD_PATH = f"{CARD_URL}/{CARD_FILE.name}"


@dataclass
class MowbiteData:
    mower: Mower
    snooze: Snooze
    app: AppSettings
    # when the cards show the map: as set in the app, while driving, always or never
    map_mode: str = "app"


type MowbiteConfigEntry = ConfigEntry[MowbiteData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """The card and what it talks to, once for all mowers."""
    websocket.async_setup(hass)
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(CARD_FILE.parent), False)])
    # a new version of the card has a new url, so browsers don't keep the old one
    version = await hass.async_add_executor_job(lambda: hashlib.sha1(CARD_FILE.read_bytes()).hexdigest()[:8])
    url = f"{CARD_PATH}?v={version}"
    add_extra_js_url(hass, url)
    await _async_card_resource(hass, url)
    return True


async def _async_card_resource(hass: HomeAssistant, url: str | None) -> None:
    """The card as a dashboard resource too, None takes it out again.

    the extra js above is part of the start page, which the app's service worker keeps from before the integration
    was there and only renews in the background: the card would be missing there until it does. dashboards load
    their resources themselves, every time. only dashboards kept by Home Assistant, yaml ones list theirs themselves
    """
    data = hass.data.get(LOVELACE_DATA)
    if data is None or not isinstance(data.resources, ResourceStorageCollection):
        return
    resources = data.resources
    await resources.async_get_info()
    mine = [item for item in resources.async_items() if item.get("url", "").split("?")[0] == CARD_PATH]
    if url is not None and not mine:
        await resources.async_create_item({"res_type": "module", "url": url})
        return
    keep = mine[:1] if url is not None else []
    for item in keep:
        if item["url"] != url:
            await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
    for item in mine[len(keep) :]:
        await resources.async_delete_item(item["id"])


async def async_setup_entry(hass: HomeAssistant, entry: MowbiteConfigEntry) -> bool:
    """Set up one mower."""
    mower = Mower(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data.get(CONF_USERNAME),
        entry.data.get(CONF_PASSWORD),
        entry.data.get(CONF_PREFIX, ""),
    )
    snooze = Snooze(hass, entry.entry_id)
    await snooze.async_load()
    app = AppSettings(hass, entry.options.get(CONF_APP_URL))
    entry.runtime_data = MowbiteData(mower, snooze, app, entry.options.get(CONF_MAP, "app"))
    entry.async_on_unload(snooze.unload)
    # the app may be off as well, the map then has the app's default colours until it's there
    entry.async_on_unload(await app.async_start())

    # a mower that's off (winter, shed) isn't an error: the entities stay unavailable and it keeps trying
    entry.async_create_background_task(hass, mower.run(), f"mowbite {mower.host}")

    @callback
    def check(_now: datetime) -> None:
        mower.check()

    entry.async_on_unload(async_track_time_interval(hass, check, timedelta(seconds=10)))

    @callback
    def notification_action(event: Event) -> None:
        action = event.data.get("action")
        if action == ACTION_SNOOZE_HOUR + entry.entry_id:
            snooze.snooze_until(dt_util.utcnow() + timedelta(hours=1))
        elif action == ACTION_SNOOZE_MORNING + entry.entry_id:
            snooze.snooze_until(next_morning())

    entry.async_on_unload(hass.bus.async_listen(EVENT_NOTIFICATION_ACTION, notification_action))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: MowbiteConfigEntry) -> None:
    """The last mower gone, the card goes from the dashboard resources too."""
    if not any(other.entry_id != entry.entry_id for other in hass.config_entries.async_entries(DOMAIN)):
        await _async_card_resource(hass, None)


async def async_unload_entry(hass: HomeAssistant, entry: MowbiteConfigEntry) -> bool:
    """Unload a mower, the background task ends with the entry."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # an open card looks for the new one
        entry.runtime_data.mower.close()
    return unloaded
