"""What to send along with a question or a bug: what the mower and the app told the integration, without logins and
without where on earth the garden is."""

from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from . import MowbiteConfigEntry
from .const import DOMAIN

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: MowbiteConfigEntry) -> dict[str, Any]:
    data = entry.runtime_data
    mower, status, app = data.mower, data.status, data.app
    integration = await async_get_integration(hass, DOMAIN)
    areas = (mower.map or {}).get("areas") or []
    return {
        "integration": str(integration.version),
        "entry": {"data": async_redact_data(dict(entry.data), TO_REDACT), "options": dict(entry.options)},
        "mower": {
            "connected": mower.connected,
            "available": mower.available,
            "robot_state": mower.state,
            "actions": mower.actions,
            "sensor_infos": mower.sensor_infos,
            "sensors": mower.sensors,
            "last_state_event": mower.last_state_event,
            "area": mower.area,
            # the map only as what's in it: its points are the garden's shape
            "map": {
                "areas": dict(Counter(str((a.get("properties") or {}).get("type")) for a in areas if isinstance(a, dict))),
                "docking_stations": len((mower.map or {}).get("docking_stations") or []),
            },
            # the place on earth is left out, only whether the mower told it
            "datum": mower.datum is not None,
            "max_position_accuracy": mower.max_position_accuracy,
            "track_points": len(mower.track.points),
        },
        "features": data.features.seen,
        "app": {
            "address_set": bool(app.url),
            "settings": sorted(app.data),
            "version": status.version,
            "level": status.level,
            "art_api": status.art_api,
            "battery_level": status.battery_level,
            "system": status.system,
            "schedule": status.schedule,
            "schedule_log": status.schedule_log,
            "battery": status.battery,
        },
        "planning": {
            "methods": sorted(data.planning.methods) if data.planning.methods is not None else None,
            "settings": sorted(data.planning.settings) if data.planning.settings else None,
            "problem": data.planning.problem,
        },
        "map_mode": data.map_mode,
        "mower_sizes": data.mower_sizes,
    }
