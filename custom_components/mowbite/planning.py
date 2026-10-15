"""The mower's plans and what its planner says, asked over rpc when something changes, never polled.

mowing.plan (OpenMower) gives the paths of an area, planner.plan (the MowBite Planner) the same paths with how long
the area takes, its mowed area and what it had to leave out. planner.leftovers and planner.drive say after a job what
stayed uncut and where the body came too close to an edge, planner.settings what the planner plans with
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging
import time
from typing import Any

import aiomqtt

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .events import SEVERITY_ERROR, SEVERITY_WARNING, Texts, interpret
from .features import EVENTS, MAP, RPC, Features
from .mower import CannotConnect, Mower, RpcError

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

# a plan takes a while when the planner has to plan it anew
PLAN_TIMEOUT = 120
# after docking the planner first reads the finished job's log
AFTER_DOCKING = 30
# an area whose plan didn't come is asked again after this long at the earliest (seconds)
RETRY_PLAN = 60


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
        if isinstance(area, dict) and (area.get("properties") or {}).get("type") == "obstacle"
    ]
    total = 0.0
    for area in areas:
        total += polygon_area(area)
        for obstacle in obstacles:
            if len(obstacle) >= 3 and _inside(obstacle[0], area):
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
        points = [p[:2] for p in path.get("points") or [] if isinstance(p, list) and len(p) >= 2]
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


def _leftover_paths(paths: Any) -> list[list[list[float]]]:
    """The leftovers' paths as point lists, whether the planner sends them as paths or as plain point lists."""
    out = []
    for path in paths or []:
        points = path.get("points") if isinstance(path, dict) else path
        points = [p[:2] for p in points or [] if isinstance(p, list) and len(p) >= 2]
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
        self._asking: set[str] = set()
        self._failed: dict[str, float] = {}
        # area id -> the job in which the mower mows only that area's leftovers
        self._leftover_runs: dict[str, str] = {}
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
        self._texts = Texts(hass.config.language)

    @callback
    def start(self) -> Callable[[], None]:
        """Listens to the mower, returns how to stop."""
        removes = [
            self._mower.add_change_listener(self._changed),
            self._mower.add_event_listener(self._event),
        ]

        def stop() -> None:
            for remove in removes:
                remove()
            if self._after_docking is not None:
                self._after_docking()

        return stop

    def has(self, method: str) -> bool:
        return self.methods is not None and method in self.methods

    @property
    def plan_method(self) -> str | None:
        """planner.plan while the MowBite Planner plans itself. Never mowing.plan then: the planner takes that for
        mower_logic fetching its plan, the job isn't timed and prepared leftovers are gone. Planning with slic3r it
        hands mowing.plan on to slic3r untouched, and only that is exactly mower_logic's plan"""
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
        return area_id is not None and job_id is not None and self._leftover_runs.get(area_id) == job_id

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
                self._ask(self._async_hello())
            else:
                self.methods = None
                self._ready = False
        if mower.map_version != self._map_version:
            self._map_version = mower.map_version
            if mow_areas(mower.map):
                self._features.add([MAP])
            self._mower.notify(KEY_PLANNING)
            if self._ready:
                self._ask(self._async_plans())
        # a job running from before Home Assistant came: the area it's on is known only from robot_state
        area_id = self.area_id
        if area_id and area_id not in self.plans and self._ready and self.plan_method:
            self._ask(self._async_plan(area_id))

    @callback
    def _event(self, event: dict[str, Any]) -> None:
        self._features.add([EVENTS])
        self._note_problem(event)
        kind = event.get("type")
        if kind == "AREA" and event.get("area_id") and self._ready and self.plan_method:
            self._ask(self._async_plan(event["area_id"]))
            if self.plan_method == PLANNER_PLAN and self.has(LOG) and isinstance(event.get("job_id"), str):
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
        if self.problem is not None and self.problem["time"] >= when:
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

    async def _async_hello(self) -> None:
        methods = await self._rpc("rpc.methods")
        if not isinstance(methods, list):
            return
        self.methods = {m for m in methods if isinstance(m, str)}
        self._features.add(RPC + method for method in self.methods)
        # which way plans are asked depends on the planner's settings, nothing is planned before they came
        await self._async_settings()
        self._ready = True
        await self._async_history()
        await self._async_after_job()

    async def _async_settings(self) -> None:
        if not self.has(SETTINGS):
            return
        result = await self._rpc(SETTINGS, {})
        if isinstance(result, dict) and isinstance(result.get("settings"), dict):
            mode = self.planner_mode
            self.settings = result["settings"]
            if self.planner_mode != mode:
                # the plans came the other way, they're asked again
                self.plans = {}
                self._plans_for = None
            self._mower.notify(KEY_PLANNING)

    async def async_set_setting(self, name: str, value: Any) -> None:
        """Changes one of the planner's settings, raises RpcError or CannotConnect. Plans are asked again."""
        result = await self._mower.async_rpc(SETTINGS_SET, {name: value})
        if isinstance(result, dict) and isinstance(result.get("settings"), dict):
            self.settings = result["settings"]
        else:
            await self._async_settings()
        self._mower.notify(KEY_PLANNING)
        self.plans = {}
        self._plans_for = None
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

    async def _async_plans(self) -> None:
        """Every active area's plan once per map, for the whole job's time and area. Not while mowing: a plan the
        planner hasn't kept costs the mower's computer time, the area being mowed is asked on its own"""
        method = self.plan_method
        mower = self._mower
        if method is None or (mower.state or {}).get("current_state") == "MOWING":
            return
        if self._plans_for == mower.map_version:
            return
        self._plans_for = mower.map_version
        self.plans = {}
        for area in mow_areas(mower.map):
            if is_active(area) and area.get("id"):
                await self._async_plan(area["id"])

    async def _async_plan(self, area_id: str) -> None:
        method = self.plan_method
        if method is None or area_id in self._asking:
            return
        if time.monotonic() - self._failed.get(area_id, -RETRY_PLAN) < RETRY_PLAN:
            return
        self._asking.add(area_id)
        try:
            # never the poses, they're about a megabyte per area
            plan = trim_plan(await self._rpc(method, {"area_id": area_id}, PLAN_TIMEOUT))
        finally:
            self._asking.discard(area_id)
        if plan is None:
            self._failed[area_id] = time.monotonic()
            return
        self._failed.pop(area_id, None)
        self.plans[area_id] = plan
        self.version += 1
        self._mower.notify(KEY_PLANNING)

    async def _async_leftover_run(self, area_id: str, job_id: str, t: Any) -> None:
        """Whether the area started is only its leftovers, the planner's log says so when mower_logic got the plan."""
        # the plan was fetched right before the area started, an older line would be from a job before
        since = (t if isinstance(t, (int, float)) else time.time()) - LEFTOVERS_BEFORE
        line = LEFTOVERS_LINE.format(area_id=area_id)
        for attempt in range(2):
            if attempt:
                await asyncio.sleep(LEFTOVERS_RECHECK)
            result = await self._rpc(LOG, {"since": since, "limit": 200})
            lines = (result or {}).get("lines") if isinstance(result, dict) else None
            if any(isinstance(entry, dict) and str(entry.get("msg", "")).startswith(line) for entry in lines or []):
                self._leftover_runs = {area_id: job_id}
                self.version += 1
                self._mower.notify(KEY_PLANNING)
                return

    async def _async_after_job(self) -> None:
        """What the last job left uncut and where it came too close to an edge, once after each job. The plans too,
        they aren't asked while mowing. The settings first, they may have been changed in the app"""
        await self._async_settings()
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
                            "left_m2": float(area.get("left_m2") or 0),
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
                            "worst": float(area.get("worst") or 0),
                            "places": [p[:3] for p in area.get("places") or [] if isinstance(p, list) and len(p) >= 3],
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
        """Gets the leftovers ready, a start in the next minutes then mows only them. Raises RpcError or CannotConnect."""
        await self._mower.async_rpc(LEFTOVERS, {"arm": True})

    async def async_reset_angle(self) -> None:
        await self._mower.async_rpc(ANGLE_RESET, {})
        self.plans = {}
        self._plans_for = None
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
