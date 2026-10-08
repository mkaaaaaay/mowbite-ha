"""The mower itself: start, pause, home."""

from __future__ import annotations

from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MowbiteConfigEntry
from .const import DOMAIN
from .entity import MowbiteEntity
from .mower import (
    ACTION_CONTINUE,
    ACTION_HOME,
    ACTION_PAUSE,
    ACTION_START,
    KEY_ACTIONS,
    KEY_STATE,
    CannotConnect,
)

PARALLEL_UPDATES = 0

# mower_logic's states. IDLE is docked or standing on the lawn (see activity), AREA_RECORDING has nothing to match,
# the state sensor shows it
ACTIVITIES = {
    "MOWING": LawnMowerActivity.MOWING,
    "UNDOCKING": LawnMowerActivity.MOWING,
    "PAUSED": LawnMowerActivity.PAUSED,
    "DOCKING": LawnMowerActivity.RETURNING,
}

# Home Assistant 2026.10 has a mower that stands still outside the dock, before that it can only be docked
IDLE = getattr(LawnMowerActivity, "IDLE", LawnMowerActivity.DOCKED)

# volts on the charging contacts above which the mower sits in the dock, also when it's fully charged and doesn't
# charge any more (MowBite tells the dock the same way)
DOCK_VOLTS = 20


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MowbiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([MowbiteLawnMower(entry)])


class MowbiteLawnMower(MowbiteEntity, LawnMowerEntity):
    """The mower."""

    _attr_name = None
    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING | LawnMowerEntityFeature.PAUSE | LawnMowerEntityFeature.DOCK
    )
    _listen = (KEY_STATE, KEY_ACTIONS, "sensor:om_v_charge")

    def __init__(self, entry: MowbiteConfigEntry) -> None:
        super().__init__(entry, "mower")
        # the state robot_state showed last and the one before it
        self._last: str | None = None
        self._before: str | None = None

    @property
    def activity(self) -> LawnMowerActivity | None:
        state = self.mower.state
        if state is None:
            return None
        if state.get("emergency"):
            return LawnMowerActivity.ERROR
        current = state.get("current_state")
        # a docking retry backs out of the dock (UNDOCKING) and tries again, it's still on its way home
        if current == "UNDOCKING" and self._before == "DOCKING":
            return LawnMowerActivity.RETURNING
        if current == "IDLE":
            return LawnMowerActivity.DOCKED if self._in_dock(state) else IDLE
        return ACTIVITIES.get(current)

    def _in_dock(self, state: dict) -> bool:
        if state.get("is_charging"):
            return True
        try:
            return float(self.mower.sensors.get("om_v_charge") or 0) > DOCK_VOLTS
        except (TypeError, ValueError):
            return False

    @callback
    def _update(self) -> None:
        current = (self.mower.state or {}).get("current_state")
        if current != self._last:
            self._before, self._last = self._last, current
        super()._update()

    async def async_start_mowing(self) -> None:
        # paused it goes on where it stopped, otherwise it starts the job
        paused = (self.mower.state or {}).get("current_state") == "PAUSED"
        await self._run(ACTION_CONTINUE if paused else ACTION_START)

    async def async_pause(self) -> None:
        await self._run(ACTION_PAUSE)

    async def async_dock(self) -> None:
        await self._run(ACTION_HOME)

    async def _run(self, action_id: str) -> None:
        # actions/json says which actions the mower takes right now, one it doesn't take would just be dropped
        if self.mower.action_enabled(action_id) is False:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="action_unavailable")
        try:
            await self.mower.async_action(action_id)
        except CannotConnect as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_connected") from err
