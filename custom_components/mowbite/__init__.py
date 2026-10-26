"""MowBite: an OpenMower in Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import logging
from pathlib import Path
import time

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from . import websocket
from .app import AppSettings, AppStatus
from .const import CONF_APP_URL, CONF_MAP, CONF_PREFIX, CONF_SIZES, DOMAIN
from .features import ACTION, APP, DATUM, Features
from .mower import KEY_ACTIONS, Mower
from .planning import Planning
from .snooze import ACTION_SNOOZE_HOUR, ACTION_SNOOZE_MORNING, Snooze, next_morning

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.DEVICE_TRACKER,
    Platform.EVENT,
    Platform.LAWN_MOWER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# what the Home Assistant app fires when a button in a notification is pressed
EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# the card comes with the integration, every dashboard can use it without adding it as a resource
CARD_URL = "/mowbite"
CARD_FILE = Path(__file__).parent / "frontend" / "mowbite-card.js"
# the app's pictures and its dashboard logic next to it, loaded by the card with the same version
ART_FILES = [CARD_FILE.parent / "mowbite-art.js", CARD_FILE.parent / "mowbite-app.js"]
CARD_PATH = f"{CARD_URL}/{CARD_FILE.name}"
# the app not answering at its address this long (s) while the mower does: a repair to check the address
APP_UNREACHABLE_AFTER = 600
# the notifications' blueprint comes with the integration too (HACS has no blueprints): into Home Assistant's
# blueprints once, unless one from this repository is there already (imported by hand). Importing it again in Home
# Assistant updates it
BLUEPRINT_FILE = Path(__file__).parent / "blueprints" / "notify.yaml"
BLUEPRINT_SOURCE = "https://github.com/mkaaaaaay/mowbite-ha/blob/main/blueprints/automation/mowbite/notify.yaml"


@dataclass
class MowbiteData:
    mower: Mower
    snooze: Snooze
    app: AppSettings
    status: AppStatus
    features: Features
    planning: Planning
    # when the cards show the map: as set in the app, while driving, always or never
    map_mode: str = "app"
    # the mower's sizes set here, for when the app has none
    mower_sizes: dict | None = None


type MowbiteConfigEntry = ConfigEntry[MowbiteData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """The card and what it talks to, once for all mowers."""
    websocket.async_setup(hass)
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(CARD_FILE.parent), False)])
    # a new version of the card has a new url, so browsers don't keep the old one
    version = await hass.async_add_executor_job(
        lambda: hashlib.sha1(b"".join(f.read_bytes() for f in [CARD_FILE, *ART_FILES])).hexdigest()[:8]
    )
    url = f"{CARD_PATH}?v={version}"
    add_extra_js_url(hass, url)
    await _async_card_resource(hass, url)
    await hass.async_add_executor_job(install_blueprint, Path(hass.config.path("blueprints", "automation")))
    return True


def install_blueprint(folder: Path) -> None:
    """Puts the blueprint into the automations' blueprints folder, once Home Assistant made it (it fills a new one
    with its own examples first)."""
    target = folder / DOMAIN / BLUEPRINT_FILE.name
    try:
        if not folder.is_dir() or target.exists():
            return
        if any(BLUEPRINT_SOURCE in path.read_text(encoding="utf-8", errors="ignore") for path in folder.glob("**/*.yaml")):
            return
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(BLUEPRINT_FILE.read_bytes())
    except OSError as err:
        _LOGGER.warning("Can't put the notifications blueprint into %s: %s", folder, err)


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
    features = Features(hass, entry.entry_id)
    await features.async_load()
    app = AppSettings(hass, entry.options.get(CONF_APP_URL))
    status = AppStatus(hass, entry.options.get(CONF_APP_URL), lambda found: features.add(APP + f for f in found))
    planning = Planning(hass, entry, mower, features)
    entry.runtime_data = MowbiteData(
        mower,
        snooze,
        app,
        status,
        features,
        planning,
        entry.options.get(CONF_MAP, "app"),
        entry.options.get(CONF_SIZES),
    )
    entry.async_on_unload(snooze.unload)
    entry.async_on_unload(planning.start())

    @callback
    def actions() -> None:
        # an action the mower lists at all, enabled or not, is one it has
        features.add(ACTION + action_id for action_id in mower.actions or {})

    entry.async_on_unload(mower.add_listener(KEY_ACTIONS, actions))

    @callback
    def datum() -> None:
        if mower.datum is not None:
            features.add([DATUM])

    entry.async_on_unload(mower.add_change_listener(datum))

    issue_id = f"app_unreachable_{entry.entry_id}"

    @callback
    def app_reach() -> None:
        # a mower that's off has its MowBite off too, that's no wrong address
        since = app.failing_since
        if since is None:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
        elif mower.available and time.monotonic() - since >= APP_UNREACHABLE_AFTER:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="app_unreachable",
                translation_placeholders={"name": entry.title, "url": app.url or ""},
            )

    entry.async_on_unload(app.add_reach_listener(app_reach))
    # a changed address or a removed mower starts again without it
    entry.async_on_unload(lambda: ir.async_delete_issue(hass, DOMAIN, issue_id))
    # the app may be off as well, the map then has the app's default colours until it's there
    entry.async_on_unload(await app.async_start())
    entry.async_on_unload(await status.async_start())

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
    await Features(hass, entry.entry_id).async_remove()
    if not any(other.entry_id != entry.entry_id for other in hass.config_entries.async_entries(DOMAIN)):
        await _async_card_resource(hass, None)


async def async_unload_entry(hass: HomeAssistant, entry: MowbiteConfigEntry) -> bool:
    """Unload a mower, the background task ends with the entry."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # an open card looks for the new one
        entry.runtime_data.mower.close()
    return unloaded
