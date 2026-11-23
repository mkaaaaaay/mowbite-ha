"""The mower's plans and what its planner says, asked over rpc when something changes, never polled.

mowing.plan (OpenMower) gives the paths of an area, planner.plan (the MowBite Planner) the same paths with how long
the area takes, its mowed area and what it had to leave out. planner.leftovers and planner.drive say after a job what
stayed uncut and where the body came too close to an edge, planner.settings what the planner plans with
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import aiomqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .events import SEVERITY_ERROR, SEVERITY_WARNING, Texts, interpret
from .features import EVENTS, MAP, RPC, Features
from .mower import CannotConnect, Mower, RpcError, finite_number, finite_numbers

_LOGGER = logging.getLogger(__name__)

# what listeners of the mower ask for when plans, leftovers or the planner's settings change
KEY_PLANNING = "planning"

PLAN = "mowing.plan"
PLANNER_PLAN = "planner.plan"
LEFTOVERS = "planner.leftovers"
DRIVE = "planner.drive"
SETTINGS = "planner.settings"
SETTINGS_SET = "planner.settings.set"
ANGLE_RESET = "planner.angle.reset"
HISTORY = "events.history"
LOG = "planner.log"
# what the planner logs when mower_logic fetches an area's plan and gets only the leftovers of the last job
LEFTOVERS_LINE = "MowBite Planner: area {area_id}, the leftovers"
# how long before the AREA event the line counts (seconds)
LEFTOVERS_BEFORE = 30
# the log is looked at again this long after the area started, the line may come a moment after the event (seconds)
LEFTOVERS_RECHECK = 10
HISTORY_LIST = "events.history.list"

# a plan takes a while when the planner has to plan it anew, after its start it plans every area ahead first
PLAN_TIMEOUT = 300
# after docking the planner first reads the finished job's log
AFTER_DOCKING = 30
# an area whose plan didn't come is asked again after this long at the earliest (seconds), on its own that many times
RETRY_PLAN = 60
RETRIES = 5
# a plan that came for a map or settings that changed meanwhile is asked again right away, this often
PLAN_TRIES = 3
# the planner's own codes for an area it can't plan as it is (error.data.code): asking again changes nothing, the
# code says why, never the text
FINAL_REFUSALS = ("BODY_OUT", "NO_PLAN", "START_UNREACHABLE")
# what the mower offers is asked again after this long when it didn't tell (seconds), each time twice as long up to
# the longest: ROS may come up after the broker, a mower without rpc never answers
HELLO_RETRY = 30
HELLO_RETRY_MAX = 600


def mow_areas(map_data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The areas to mow in the map's order, inactive ones too (current_area counts them)."""
    if not isinstance(map_data, dict):
        return []
    return [
        area
        for area in map_data.get("areas") or []
        if isinstance(area, dict) and (area.get("properties") or {}).get("type") == "mow"
    ]


def is_active(area: dict[str, Any]) -> bool:
    properties = area.get("properties") or {}
    return properties.get("active") is not False and properties.get("mowable") is not False


def _points(outline: Any) -> list[tuple[float, float]]:
    points = []
    for point in outline or []:
        if isinstance(point, dict) and isinstance(point.get("x"), (int, float)):
            points.append((float(point["x"]), float(point.get("y") or 0)))
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            points.append((float(point[0]), float(point[1])))
    return points


def polygon_area(points: list[tuple[float, float]]) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))) / 2


def _inside(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def lawn_area(map_data: dict[str, Any] | None) -> float | None:
    """The active areas to mow less the obstacles in them (m²), from the map alone."""
    areas = [_points(area.get("outline")) for area in mow_areas(map_data) if is_active(area)]
    areas = [area for area in areas if len(area) >= 3]
    if not areas:
        return None
    obstacles = [
        _points(area.get("outline"))
        for area in (map_data or {}).get("areas") or []
        if isinstance(area, dict) and (area.get("properties") or {}).get("type") == "obstacle" and is_active(area)
    ]
    total = 0.0
    for area in areas:
        total += polygon_area(area)
        for obstacle in obstacles:
            # only an obstacle wholly in the area, one across its edge would need clipping
            if len(obstacle) >= 3 and all(_inside(point, area) for point in obstacle):
                total -= polygon_area(obstacle)
    return max(total, 0.0)


def trim_plan(result: Any) -> dict[str, Any] | None:
    """What's kept of mowing.plan's or planner.plan's answer: the paths, and the planner's time and area."""
    if not isinstance(result, dict) or not isinstance(result.get("paths"), list):
        return None
    paths = []
    for path in result["paths"]:
        if not isinstance(path, dict):
            continue
        points = _numbers(path.get("points"), 2)
        index = [i for i in path.get("pose_index") or [] if isinstance(i, int)]
        if len(index) != len(points):
            index = []
        poses = path.get("poses")
        if not isinstance(poses, int):
            poses = index[-1] + 1 if index else len(points)
        paths.append({"outline": bool(path.get("is_outline")), "points": points, "pose_index": index, "poses": poses})
    duration = result.get("duration") if isinstance(result.get("duration"), dict) else {}
    stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
    minutes = duration.get("min")
    area = stats.get("area")
    return {
        "area_id": result.get("area_id"),
        "paths": paths,
        "minutes": float(minutes) if isinstance(minutes, (int, float)) else None,
        "area": float(area) if isinstance(area, (int, float)) else None,
        "warnings": [w for w in result.get("warnings") or [] if isinstance(w, str)],
        "fingerprint": result.get("fingerprint"),
    }


def plan_progress(plan: dict[str, Any] | None, path: Any, pose: Any) -> float | None:
    """How far the mower is through the plan (0..1), from robot_state's current_path and current_path_index."""
    if not plan or not isinstance(path, int) or not isinstance(pose, int) or path < 0 or pose < 0:
        return None
    paths = plan["paths"]
    total = sum(p["poses"] for p in paths)
    if not total or path >= len(paths):
        return None
    done = sum(p["poses"] for p in paths[:path]) + min(pose, paths[path]["poses"])
    return min(done / total, 1.0)


def _numbers(points: Any, count: int) -> list[list[float]]:
    """Of a list of points those that are count finite numbers, the card writes them into its svg."""
    found = (finite_numbers(point, count) for point in (points if isinstance(points, list) else []))
    return [point for point in found if point is not None]


def _leftover_paths(paths: Any) -> list[list[list[float]]]:
    """The leftovers' paths as point lists, whether the planner sends them as paths or as plain point lists."""
    out = []
    for path in paths if isinstance(paths, list) else []:
        points = _numbers(path.get("points") if isinstance(path, dict) else path, 2)
        if len(points) >= 2:
            out.append(points)
    return out


class Planning:
    """Plans and the planner's answers for one mower, refreshed on the events that change them."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, mower: Mower, features: Features) -> None:
        self._hass = hass
        self._entry = entry
        self._mower = mower
        self._features = features
        # the methods rpc.methods listed, None until the mower answered
        self.methods: set[str] | None = None
        # the methods and the planner's settings are known
        self._ready = False
        # area id -> trimmed plan, for the map as it was when they were asked
        self.plans: dict[str, dict[str, Any]] = {}
        self._plans_for: int | None = None
        # area id -> the planner's code for why it can't plan it (FINAL_REFUSALS), for that map and those settings
        self.refused: dict[str, str] = {}
        # goes up when the plans are dropped, an answer asked before is for what was
        self._plans_version = 0
        self._asking: set[str] = set()
        self._failed: dict[str, float] = {}
        # area id -> how often its plan was asked again on its own for this map, and the wait for the next time
        self._retries: dict[str, int] = {}
        self._retrying: dict[str, Callable[[], None]] = {}
        # (job id, area id) of areas a job mows only the leftovers of, until the job ends. a job that heads home
        # (rain, battery) and comes back starts the area again without fetching its plan anew, it stays a leftover run
        self._leftover_runs: set[tuple[str, str]] = set()
        # when each job left the dock first, a log line from before can't be its own
        self._job_starts: dict[str, float] = {}
        self.leftovers: dict[str, Any] | None = None
        self.drive: dict[str, Any] | None = None
        self.settings: dict[str, Any] | None = None
        # the newest warning or error the mower had, as the event entity tells it
        self.problem: dict[str, Any] | None = None
        # goes up whenever something the card draws changed
        self.version = 0
        self._connected = False
        self._map_version = -1
        self._after_docking: Callable[[], None] | None = None
        # robot_state came and wasn't stale: ROS is up
        self._available = False
        self._hello_running = False
        self._hello_again = False
        self._hello_retry: Callable[[], None] | None = None
        self._hello_wait = HELLO_RETRY
        self._stopped = False
        self._texts = Texts(hass.config.language)

    @callback
    def start(self) -> Callable[[], None]:
        """Listens to the mower, returns how to stop."""
        removes = [
            self._mower.add_change_listener(self._changed),
            self._mower.add_event_listener(self._event),
        ]

        def stop() -> None:
            self._stopped = True
            for remove in removes:
                remove()
            self._cancel_hello_retry()
            if self._after_docking is not None:
                self._after_docking()
            for cancel in self._retrying.values():
                cancel()
            self._retrying.clear()

        return stop

    def has(self, method: str) -> bool:
        return self.methods is not None and method in self.methods

    @property
    def plan_method(self) -> str | None:
        """planner.plan while the MowBite Planner plans itself. Never mowing.plan then: the planner takes that for
        mower_logic fetching its plan, the job isn't timed and prepared leftovers are gone. Planning with slic3r it
        hands mowing.plan on to slic3r untouched, and only that is exactly mower_logic's plan. None while a planner
        with settings hasn't told them: which of the two it is isn't known then"""
        if self.has(SETTINGS) and self.settings is None:
            return None
        if self.has(PLANNER_PLAN) and self.planner_mode != "slic3r":
            return PLANNER_PLAN
        if self.has(PLAN):
            return PLAN
        return None

    @property
    def planner_mode(self) -> str | None:
        """Who plans for the MowBite Planner: "mowbite" itself or "slic3r", None without its settings."""
        value = ((self.settings or {}).get("planner") or {}).get("value")
        return value if isinstance(value, str) else None

    # what the sensors show

    @property
    def area_id(self) -> str | None:
        """The area being mowed: from its AREA event, or robot_state's index into the map's areas to mow."""
        state = self._mower.state or {}
        if state.get("current_state") != "MOWING":
            return None
        if self._mower.area_id:
            return self._mower.area_id
        index = state.get("current_area")
        areas = mow_areas(self._mower.map)
        if isinstance(index, int) and 0 <= index < len(areas):
            return areas[index].get("id")
        return None

    @property
    def area_name(self) -> str | None:
        area_id = self.area_id
        if area_id is None:
            return None
        for area in mow_areas(self._mower.map):
            if area.get("id") == area_id:
                return (area.get("properties") or {}).get("name") or self._mower.area
        return self._mower.area

    @property
    def leftover_run(self) -> bool:
        """Whether the mower mows only the leftovers of the area: robot_state's path then counts in the leftovers,
        not in the area's plan, there's no progress or time to tell"""
        area_id = self.area_id
        job_id = (self._mower.position or {}).get("job_id")
        return area_id is not None and job_id is not None and (job_id, area_id) in self._leftover_runs

    @property
    def progress(self) -> float | None:
        """How far through the area being mowed (0..1)."""
        area_id = self.area_id
        if area_id is None or self.leftover_run:
            return None
        state = self._mower.state or {}
        return plan_progress(self.plans.get(area_id), state.get("current_path"), state.get("current_path_index"))

    @property
    def area_minutes_left(self) -> float | None:
        """The planner's time for the area being mowed, less what's done."""
        area_id = self.area_id
        plan = self.plans.get(area_id or "")
        progress = self.progress
        if plan is None or plan["minutes"] is None or progress is None:
            return None
        return plan["minutes"] * (1 - progress)

    @property
    def job_minutes_left(self) -> float | None:
        """The area being mowed plus the active areas the job hasn't got to yet."""
        left = self.area_minutes_left
        if left is None:
            return None
        job_id = (self._mower.position or {}).get("job_id")
        done = set(self._mower.job_areas.get(job_id or "", []))
        for area in mow_areas(self._mower.map):
            area_id = area.get("id")
            if not is_active(area) or area_id in done or area_id == self.area_id:
                continue
            plan = self.plans.get(area_id)
            if plan is None or plan["minutes"] is None:
                return None
            left += plan["minutes"]
        return left

    @property
    def lawn_area(self) -> float | None:
        """What a whole job mows (m²): the planner's areas when it planned all of them, otherwise from the map."""
        active = [area.get("id") for area in mow_areas(self._mower.map) if is_active(area)]
        plans = [self.plans.get(area_id) for area_id in active]
        if active and all(plan is not None and plan["area"] is not None for plan in plans):
            return sum(plan["area"] for plan in plans if plan)
        return lawn_area(self._mower.map)

    @property
    def job_minutes(self) -> float | None:
        """How long a whole job takes, by the planner."""
        active = [area.get("id") for area in mow_areas(self._mower.map) if is_active(area)]
        plans = [self.plans.get(area_id) for area_id in active]
        if not active or not all(plan is not None and plan["minutes"] is not None for plan in plans):
            return None
        return sum(plan["minutes"] for plan in plans if plan)

    @property
    def leftover_m2(self) -> float | None:
        if self.leftovers is None:
            return None
        return sum(area["left_m2"] for area in self.leftovers["areas"].values())

    @property
    def leftover_paths(self) -> list[list[list[float]]]:
        if self.leftovers is None:
            return []
        return [path for area in self.leftovers["areas"].values() for path in area["paths"]]

    @property
    def worst_margin(self) -> float | None:
        if self.drive is None:
            return None
        return max((area["worst"] for area in self.drive["areas"].values()), default=0.0)

    # what makes something to ask

    @callback
    def _changed(self) -> None:
        mower = self._mower
        if mower.connected != self._connected:
            self._connected = mower.connected
            if mower.connected:
                self._hello()
            else:
                self.methods = None
                self._ready = False
                self._cancel_hello_retry()
                self._hello_wait = HELLO_RETRY
        if mower.available != self._available:
            self._available = mower.available
            # the broker may have been up before ROS, rpc.methods had no answer then
            if mower.available and self.methods is None:
                self._hello()
        if mower.map_version != self._map_version:
            self._map_version = mower.map_version
            if mow_areas(mower.map):
                self._features.add([MAP])
            self._mower.notify(KEY_PLANNING)
            if self._ready:
                self._ask(self._async_plans())
        # a job running from before Home Assistant came: the area it's on is known only from robot_state
        area_id = self.area_id
        if area_id and area_id not in self.plans and area_id not in self.refused and self._ready and self.plan_method:
            self._ask(self._async_plan(area_id))

    @callback
    def _event(self, event: dict[str, Any]) -> None:
        self._features.add([EVENTS])
        self._note_problem(event)
        kind = event.get("type")
        job_id = event.get("job_id")
        if kind == "STATE" and event.get("state") == "UNDOCKING" and isinstance(job_id, str):
            if isinstance(event.get("t"), (int, float)) and job_id not in self._job_starts:
                self._job_starts[job_id] = event["t"]
                for old in list(self._job_starts)[:-5]:
                    del self._job_starts[old]
        elif kind in ("JOB_COMPLETE", "JOB_RESET"):
            self._leftover_runs = {run for run in self._leftover_runs if run[0] != job_id}
        elif kind == "BOOTED":
            # ROS started anew while the broker stayed, what it offers and its planner's settings may have changed
            self._hello()
        if kind == "AREA" and event.get("area_id") and self._ready and self.plan_method:
            self._ask(self._async_plan(event["area_id"]))
            if (
                self.plan_method == PLANNER_PLAN
                and self.has(LOG)
                and isinstance(job_id, str)
                and (job_id, event["area_id"]) not in self._leftover_runs
            ):
                self._ask(self._async_leftover_run(event["area_id"], event["job_id"], event.get("t")))
        elif kind == "DOCKED":
            if self._after_docking is not None:
                self._after_docking()

            @callback
            def after(_now: Any) -> None:
                self._after_docking = None
                self._ask(self._async_after_job())

            self._after_docking = async_call_later(self._hass, AFTER_DOCKING, after)

    def _note_problem(self, event: dict[str, Any]) -> None:
        found = interpret(event, None, self._texts)
        if found is None:
            return
        event_type, attributes = found
        if attributes.get("severity") not in (SEVERITY_ERROR, SEVERITY_WARNING):
            return
        t = event.get("t")
        when = dt_util.utc_from_timestamp(t) if isinstance(t, (int, float)) else dt_util.utcnow()
        # the same time again is the same problem told once more, with more to it (an emergency stop's reason)
        if self.problem is not None and self.problem["time"] > when:
            return
        self.problem = {
            "time": when,
            "type": event_type,
            "message": attributes.get("message"),
            "severity": attributes.get("severity"),
        }
        self._mower.notify(KEY_PLANNING)

    def _ask(self, coro: Any) -> None:
        self._entry.async_create_background_task(self._hass, coro, f"mowbite planning {self._mower.host}")

    async def _rpc(self, method: str, params: Any = None, timeout: float = 20) -> Any:
        """None when the mower doesn't answer, logged, it's asked again on the next change."""
        try:
            return await self._mower.async_rpc(method, params, timeout)
        except (RpcError, CannotConnect, TimeoutError, aiomqtt.MqttError) as err:
            _LOGGER.debug("%s didn't answer %s: %s", self._mower.host, method, err)
            return None

    @callback
    def _hello(self) -> None:
        """Asks what the mower offers and how its planner is set, once at a time."""
        if not self._mower.connected:
            return
        if self._hello_running:
            # something changed while it was being asked: once more after this one
            self._hello_again = True
            return
        self._cancel_hello_retry()
        self._hello_running = True
        self._ask(self._async_hello())

    async def _async_hello(self) -> None:
        told = False
        try:
            methods = await self._rpc("rpc.methods")
            if not isinstance(methods, list):
                return
            self.methods = {m for m in methods if isinstance(m, str)}
            self._features.add(RPC + method for method in self.methods)
            # which way plans are asked depends on the planner's settings, nothing is planned before they came
            if not await self._async_settings():
                return
            told = True
            self._ready = True
            self._hello_wait = HELLO_RETRY
            await self._async_history()
            await self._async_after_job()
        finally:
            self._hello_running = False
            if self._hello_again:
                self._hello_again = False
                self._hello()
            elif not told:
                self._retry_hello()

    @callback
    def _retry_hello(self) -> None:
        if self._stopped or not self._mower.connected or self._hello_retry is not None:
            return

        @callback
        def again(_now: Any) -> None:
            self._hello_retry = None
            self._hello()

        self._hello_retry = async_call_later(self._hass, self._hello_wait, again)
        self._hello_wait = min(self._hello_wait * 2, HELLO_RETRY_MAX)

    @callback
    def _cancel_hello_retry(self) -> None:
        if self._hello_retry is not None:
            self._hello_retry()
            self._hello_retry = None

    def _forget_plans(self) -> None:
        """The plans were for other settings, one still on its way is too. All of them are asked again."""
        self.plans = {}
        self.refused = {}
        self._plans_for = None
        self._plans_version += 1

    async def _async_settings(self) -> bool:
        """Reads the planner's settings, False when it has some and didn't tell them."""
        if not self.has(SETTINGS):
            return True
        result = await self._rpc(SETTINGS, {})
        if not isinstance(result, dict) or not isinstance(result.get("settings"), dict):
            return False
        mode = self.planner_mode
        self.settings = result["settings"]
        if self.planner_mode != mode:
            # the plans came the other way
            self._forget_plans()
        self._mower.notify(KEY_PLANNING)
        return True

    async def async_plan_method(self) -> str | None:
        """plan_method with the planner's settings as they are right now, they may have been changed in the app."""
        return self.plan_method if await self._async_settings() else None

    async def async_set_setting(self, name: str, value: Any) -> None:
        """Changes one of the planner's settings, raises RpcError or CannotConnect. Plans are asked again."""
        result = await self._mower.async_rpc(SETTINGS_SET, {name: value})
        if isinstance(result, dict) and isinstance(result.get("settings"), dict):
            self.settings = result["settings"]
        else:
            await self._async_settings()
        self._mower.notify(KEY_PLANNING)
        self._forget_plans()
        self._ask(self._async_plans())

    async def _async_history(self) -> None:
        """Today's and yesterday's events: the newest problem, and the areas the running job got to."""
        if not self.has(HISTORY):
            return
        self._features.add([EVENTS])
        today = dt_util.now()
        for day in (today - timedelta(days=1), today):
            events = await self._rpc(HISTORY, {"date": day.strftime("%Y%m%d")})
            for event in events if isinstance(events, list) else []:
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "AREA":
                    self._mower.add_job_area(event.get("job_id"), event.get("area_id"))
                self._note_problem(event)

    @property
    def _busy(self) -> bool:
        """The mower drives or mows: a plan the planner hasn't kept costs its computer time then."""
        return (self._mower.state or {}).get("current_state") not in (None, "IDLE")

    async def _async_plans(self) -> None:
        """Every active area's plan once per map, for the whole job's time and area, after a job the ones that didn't
        come. Only while the mower is idle, looked at before each area, the area being mowed is asked on its own"""
        mower = self._mower
        if self._busy:
            return
        # once for all of them: how the planner plans may have been changed in the app
        told = await self._async_settings()
        if told and self.plan_method is None:
            return
        if self._plans_for != mower.map_version:
            self._plans_for = mower.map_version
            self.plans = {}
            self.refused = {}
            self._retries = {}
        for area in mow_areas(mower.map):
            if self._busy:
                return
            area_id = area.get("id")
            if is_active(area) and area_id and area_id not in self.plans and area_id not in self.refused:
                await self._async_plan(area_id, told)

    async def _async_plan(self, area_id: str, told: bool = False) -> None:
        """told: the planner's settings were read just now."""
        if area_id in self._asking or area_id in self.refused:
            return
        if time.monotonic() - self._failed.get(area_id, -RETRY_PLAN) < RETRY_PLAN:
            return
        self._asking.add(area_id)
        try:
            plan, refused = await self._async_ask_plan(area_id, told)
        finally:
            self._asking.discard(area_id)
        if plan is None and refused is None:
            self._failed[area_id] = time.monotonic()
            self._retry(area_id)
            return
        self._failed.pop(area_id, None)
        self._retries.pop(area_id, None)
        if plan is not None:
            self.plans[area_id] = plan
        else:
            self.refused[area_id] = refused
        self.version += 1
        self._mower.notify(KEY_PLANNING)

    async def _async_ask_plan(self, area_id: str, told: bool) -> tuple[dict[str, Any] | None, str | None]:
        """The area's plan, or the planner's code for why there is none, neither when it didn't come."""
        mower = self._mower
        for _ in range(PLAN_TRIES):
            # the settings first: a planner switched to planning itself in the app must not get mowing.plan
            if not told and not await self._async_settings():
                return None, None
            told = False
            method = self.plan_method
            if method is None:
                return None, None
            asked = (mower.map_version, self._plans_version)
            refused = None
            try:
                # never the poses, they're about a megabyte per area
                plan = trim_plan(await mower.async_rpc(method, {"area_id": area_id}, PLAN_TIMEOUT))
            except RpcError as err:
                _LOGGER.debug("%s didn't answer %s for %s: %s", mower.host, method, area_id, err)
                code = err.data.get("code") if isinstance(err.data, dict) else None
                plan, refused = None, code if code in FINAL_REFUSALS else None
            except (CannotConnect, TimeoutError, aiomqtt.MqttError) as err:
                _LOGGER.debug("%s didn't answer %s for %s: %s", mower.host, method, area_id, err)
                return None, None
            # an answer for a map or settings that changed while the planner worked is the old one's
            if asked == (mower.map_version, self._plans_version):
                return plan, refused
        return None, None

    @callback
    def _retry(self, area_id: str) -> None:
        """Asks a plan that didn't come again after a while, a few times: the planner may have been planning every
        area ahead after its start, the next change of the map or the next job is too far off"""
        tries = self._retries.get(area_id, 0)
        if tries >= RETRIES or area_id in self._retrying:
            return
        self._retries[area_id] = tries + 1

        @callback
        def again(_now: Any) -> None:
            self._retrying.pop(area_id, None)
            mower = self._mower
            # only while idle, the area being mowed is asked on its own, and not an area the map lost
            if area_id in self.plans or not self._ready or not mower.connected:
                return
            if self._busy:
                return
            if not any(area.get("id") == area_id and is_active(area) for area in mow_areas(mower.map)):
                return
            self._failed.pop(area_id, None)
            self._ask(self._async_plan(area_id))

        self._retrying[area_id] = async_call_later(self._hass, RETRY_PLAN, again)

    async def _async_leftover_run(self, area_id: str, job_id: str, t: Any) -> None:
        """Whether the area started is only its leftovers, the planner's log says so when mower_logic got the plan."""
        # the plan was fetched right before the area started, and not before the job left the dock
        since = (t if isinstance(t, (int, float)) else time.time()) - LEFTOVERS_BEFORE
        since = max(since, self._job_starts.get(job_id, since))
        line = LEFTOVERS_LINE.format(area_id=area_id)
        for attempt in range(2):
            if attempt:
                await asyncio.sleep(LEFTOVERS_RECHECK)
            result = await self._rpc(LOG, {"since": since, "limit": 200})
            lines = (result or {}).get("lines") if isinstance(result, dict) else None
            if any(isinstance(entry, dict) and str(entry.get("msg", "")).startswith(line) for entry in lines or []):
                self._leftover_runs.add((job_id, area_id))
                self.version += 1
                self._mower.notify(KEY_PLANNING)
                return

    async def _async_after_job(self) -> None:
        """What the last job left uncut and where it came too close to an edge, once after each job. The plans too,
        they aren't asked while mowing (with the settings first, they may have been changed in the app)"""
        await self._async_plans()
        changed = False
        if self.has(LEFTOVERS):
            result = await self._rpc(LEFTOVERS, {})
            if isinstance(result, dict) and isinstance(result.get("areas"), dict):
                self.leftovers = {
                    "file": result.get("file"),
                    "armed": result.get("armed") or 0,
                    "areas": {
                        area_id: {
                            "left_m2": finite_number(area.get("left_m2")) or 0.0,
                            "paths": _leftover_paths(area.get("paths")),
                            "message": area.get("message"),
                        }
                        for area_id, area in result["areas"].items()
                        if isinstance(area, dict)
                    },
                }
                changed = True
        if self.has(DRIVE):
            result = await self._rpc(DRIVE, {})
            if isinstance(result, dict) and isinstance(result.get("areas"), dict):
                self.drive = {
                    "file": result.get("file"),
                    "areas": {
                        area_id: {
                            "worst": finite_number(area.get("worst")) or 0.0,
                            "places": _numbers(area.get("places"), 3),
                        }
                        for area_id, area in result["areas"].items()
                        if isinstance(area, dict)
                    },
                }
                changed = True
        if changed:
            self.version += 1
            self._mower.notify(KEY_PLANNING)

    async def async_arm_leftovers(self) -> None:
        """Gets the leftovers ready, a start in the next minutes then mows only them. Raises RpcError (also when the
        planner has none to get ready: the start would mow everything), CannotConnect or TimeoutError."""
        result = await self._mower.async_rpc(LEFTOVERS, {"arm": True})
        if not isinstance(result, dict) or not result.get("armed"):
            raise RpcError("no leftovers armed")

    async def async_reset_angle(self) -> None:
        await self._mower.async_rpc(ANGLE_RESET, {})
        self._forget_plans()
        self._ask(self._async_plans())

    def card(self) -> dict[str, Any]:
        """What the card draws: the plan of the area being mowed with how far it got, the leftovers, tight places."""
        area_id = self.area_id
        plan = self.plans.get(area_id or "")
        state = self._mower.state or {}
        if self.leftover_run:
            plan = None
        return {
            "plan": {"area_id": area_id, "paths": plan["paths"]} if plan else None,
            "plan_at": [state.get("current_path"), state.get("current_path_index")] if plan else None,
            "leftovers": self.leftover_paths,
            "tight": [p for area in (self.drive or {}).get("areas", {}).values() for p in area["places"]],
        }
