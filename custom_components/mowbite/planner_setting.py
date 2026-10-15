"""The base of the entities for the planner's settings: changed only while the mower is idle."""

from __future__ import annotations

from typing import Any

from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from . import MowbiteConfigEntry
from .const import DOMAIN
from .entity import MowbiteEntity
from .mower import KEY_STATE, CannotConnect, RpcError
from .planning import KEY_PLANNING, Planning


class MowbitePlannerSetting(MowbiteEntity):
    """One of planner.settings. A change while mowing would plan an area anew and start it over, so only idle"""

    _attr_entity_category = EntityCategory.CONFIG
    _listen = (KEY_STATE, KEY_PLANNING)

    def __init__(self, entry: MowbiteConfigEntry, setting: str) -> None:
        super().__init__(entry, f"planner_{setting}")
        self._setting = setting
        self._planning: Planning = entry.runtime_data.planning

    @property
    def _info(self) -> dict[str, Any] | None:
        info = (self._planning.settings or {}).get(self._setting)
        return info if isinstance(info, dict) and info.get("settable") else None

    @property
    def available(self) -> bool:
        return super().available and self._info is not None

    @property
    def setting_value(self) -> Any:
        return (self._info or {}).get("value")

    async def async_set_setting(self, value: Any) -> None:
        if (self.mower.state or {}).get("current_state") != "IDLE":
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="only_idle")
        try:
            await self._planning.async_set_setting(self._setting, value)
        except CannotConnect as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_connected") from err
        except (RpcError, TimeoutError) as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="planner_failed") from err
