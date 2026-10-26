"""The MowBite app's own settings: the map's colours and symbols as they're set in the app."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
import json
import logging
import re
import time
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

# the app keeps them in its container, the same for every device (docker/settings.cgi)
SETTINGS_PATH = "/cgi-bin/settings"
# a change in the app shows on the card a minute later at the latest
REFRESH = timedelta(minutes=1)
# what the card uses of them: the map's colors, icons, style, pictures per area and garden life, the mower's sizes,
# whether the weather may be asked
KEYS = (
    "colors",
    "icons",
    "dashboard",
    "mower",
    "mapStyle",
    "looks",
    "lookVariants",
    "lookSizes",
    "lookTurns",
    "lookClosed",
    "lookGrounds",
    "keepRectangle",
    "garden",
    "weather",
)


# without a MowBite address there's no app to go by: the map always shown, plain like the app's own default (a card
# can still have the garden, map_style)
WITHOUT_APP: dict[str, Any] = {"dashboard": {"map": "always"}}


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
    return {key: data[key] for key in KEYS if data.get(key) is not None}


class AppSettings:
    """The app's settings, read again every few minutes, WITHOUT_APP without an address."""

    def __init__(self, hass: HomeAssistant, url: str | None) -> None:
        self._hass = hass
        self._url = url
        self.data: dict[str, Any] = {} if url else WITHOUT_APP
        self.version = 0
        self._listeners: list[Callable[[], None]] = []
        # since when the app doesn't answer at its address (monotonic), None while it does
        self.failing_since: float | None = None
        self._reach_listeners: list[Callable[[], None]] = []

    @property
    def url(self) -> str | None:
        return self._url

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def add_reach_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Called after every time the app was asked, whether it answered or not."""
        self._reach_listeners.append(listener)
        return lambda: self._reach_listeners.remove(listener)

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
            if self.failing_since is None:
                self.failing_since = time.monotonic()
            self._reached()
            return
        self.failing_since = None
        self._reached()
        if data != self.data:
            self.data = data
            self.version += 1
            for listener in list(self._listeners):
                listener()

    def _reached(self) -> None:
        for listener in list(self._reach_listeners):
            listener()


# what the app's container tells about the mower's computer, its schedule and its battery, plain text lines of
# "key value ..." (docker/*.cgi in MowBite, the same since 1.3.0)
VERSION_PATH = "/version.json"
SYSTEM_PATH = "/cgi-bin/system"
SCHEDULE_PATH = "/cgi-bin/schedule"
SCHEDULE_LOG_PATH = "/cgi-bin/schedule?log"
BATTERY_PATH = "/cgi-bin/battery"
# blade time, distances and runs per hour and in total, and the parts' maintenance (docker/stats.cgi)
STATS_PATH = "/cgi-bin/stats"
# MowBite's own battery level (containers of level 4 on): it stays put when the mower sets off, where OpenMower's
# percentage (a line through the voltage) drops, and 0 % is where OpenMower sends it home. asked every refresh
BATTERY_LEVEL_PATH = "/cgi-bin/battery?level"
BATTERY_LEVEL_FROM = 4
# good for this long after MowBite worked it out (s)
BATTERY_LEVEL_FRESH = 120
# the map's pictures, the app's own mowers, docks and garden (MowBite 1.4 and newer), and how big they may be
ART_PATH = "/mowbite-art.js"
ART_MAX = 4_000_000
STATUS_REFRESH = timedelta(minutes=1)
# the slower ones every so many refreshes
SCHEDULE_EVERY = 5
BATTERY_EVERY = 15
VERSION_EVERY = 60

# what the schedule log says when it didn't start, the reason after "skip_"
SKIP_REASONS = ["rain", "forecast", "dark", "battery", "busy", "offline", "emergency", "paused"]


def _lines(text: str) -> list[list[str]]:
    return [line.split() for line in text.splitlines() if line.strip()]


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def parse_system(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for words in _lines(text):
        if len(words) >= 2:
            values = [_number(word) for word in words[1:]]
            out[words[0]] = values if len(values) > 1 else values[0]
    return out


def parse_schedule(text: str) -> dict[str, Any]:
    """Whether it's on, how many plans and when they start: "plan <days> <HH:MM> [areas] [end=HH:MM] ...", days 1 =
    monday .. 7 = sunday, local time, and "pause <YYYY-MM-DD> all|<areas>" (MowBite's schedule.ts)"""
    out: dict[str, Any] = {"enabled": False, "plans": 0, "starts": [], "pause": None}
    for words in _lines(text):
        if words[0] == "enabled" and len(words) >= 2:
            out["enabled"] = words[1] == "1"
        elif words[0] == "plan":
            out["plans"] += 1
            if len(words) < 3 or not _hhmm(words[2]):
                continue
            days = [int(d) for d in words[1].split(",") if d.isdigit() and 1 <= int(d) <= 7]
            end = next((w[4:] for w in words[3:] if w.startswith("end=") and _hhmm(w[4:])), None)
            areas = next((w.split(",") for w in words[3:] if "=" not in w), [])
            out["starts"].append({"days": days, "time": words[2], "end": end, "areas": areas})
        elif words[0] == "pause" and len(words) >= 3 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", words[1]):
            out["pause"] = {"until": words[1], "areas": "all" if words[2] == "all" else words[2].split(",")}
    return out


def _hhmm(text: str) -> bool:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    return match is not None and int(match[1]) < 24 and int(match[2]) < 60


def _at(day: date, hhmm: str, tz: Any) -> datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def schedule_starts(schedule: dict[str, Any] | None, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """The plans' starts from start to end in start's time zone, oldest first, none while the schedule is off or
    paused for the whole day: [{"start", "end", "areas"}], end the plan's or None"""
    if not schedule or not schedule["enabled"]:
        return []
    pause = schedule.get("pause")
    tz = start.tzinfo
    out = []
    day = start.date() - timedelta(days=1)
    while day <= end.date():
        paused = pause is not None and pause["areas"] == "all" and day.isoformat() <= pause["until"]
        for plan in [] if paused else schedule["starts"]:
            if day.isoweekday() not in plan["days"]:
                continue
            at = _at(day, plan["time"], tz)
            until = _at(day, plan["end"], tz) if plan["end"] else None
            if until is not None and until <= at:
                until += timedelta(days=1)
            if start <= (until or at) and at < end:
                out.append({"start": at, "end": until, "areas": plan["areas"]})
        day += timedelta(days=1)
    return sorted(out, key=lambda s: s["start"])


def next_start(schedule: dict[str, Any] | None, now: datetime) -> datetime | None:
    """When the schedule starts the mower next (MowBite's nextStart, without what the scheduler may still leave out:
    the dark, rain, a low battery)"""
    later = [s["start"] for s in schedule_starts(schedule, now, now + timedelta(days=8)) if s["start"] > now]
    return later[0] if later else None


def parse_stats(text: str) -> dict[str, Any]:
    """MowBite's counts (stats.ts): blade seconds, m driven with the blade on (mowed) and off (driven) and runs, in
    total and per hour ("hour <unix s> ..."), and each part's maintenance ("maint <part> <due blade hours> <blade
    seconds when done> <done at>")"""
    out: dict[str, Any] = {"since": None, "total": None, "hours": [], "parts": {}}
    for words in _lines(text):
        n = [_number(w) for w in words[1:]]
        if words[0] == "since" and n and n[0] is not None:
            out["since"] = n[0]
        elif words[0] == "total" and len(n) >= 4 and None not in n[:4]:
            out["total"] = dict(zip(("blade", "mowed", "driven", "runs"), n[:4], strict=True))
        elif words[0] == "hour" and len(n) >= 5 and None not in n[:5]:
            out["hours"].append(dict(zip(("t", "blade", "mowed", "driven", "runs"), n[:5], strict=True)))
        elif words[0] == "maint" and len(words) >= 5 and None not in n[1:4]:
            out["parts"][words[1]] = {"due_hours": n[1], "base_blade": n[2], "done_at": n[3]}
    return out


def stats_since(stats: dict[str, Any] | None, since: float) -> dict[str, float] | None:
    """The counts of the hours from since (unix s) on, today's from the local day's start"""
    if not stats or stats["total"] is None:
        return None
    hours = [h for h in stats["hours"] if h["t"] >= since]
    return {key: sum(h[key] for h in hours) for key in ("blade", "mowed", "driven", "runs")}


def part_hours_left(stats: dict[str, Any] | None, part: str) -> float | None:
    """Blade hours until the part is due again (0 when it is), MowBite's partUse"""
    p = (stats or {}).get("parts", {}).get(part)
    if p is None or not stats or stats["total"] is None or not p["due_hours"]:
        return None
    used = max(0.0, stats["total"]["blade"] - p["base_blade"]) / 3600
    return max(0.0, p["due_hours"] - used)


def parse_schedule_log(text: str) -> dict[str, Any]:
    """The newest start and the newest time it didn't start, with why."""
    out: dict[str, Any] = {"started": None, "skipped": None, "skip_reason": None}
    for words in _lines(text):
        t = _number(words[0])
        if t is None or len(words) < 2:
            continue
        if words[1] == "started":
            out["started"] = t
        elif words[1].startswith("skip_"):
            out["skipped"] = t
            out["skip_reason"] = words[1][len("skip_") :]
    return out


# how far back the longest run counts (seconds)
BATTERY_WINDOW = 30 * 86400


def parse_battery(text: str, now: float) -> dict[str, Any]:
    """The longest run of the last 30 days: how long the blade ran on one charge, and the voltage it went down to.
    Most runs end before the battery is empty (the job's done, rain), the longest is what a charge lasts, and it gets
    shorter as the battery ages"""
    out: dict[str, Any] = {"blade_minutes": None, "run_end": None, "low_voltage": None}
    for words in _lines(text):
        if words[0] != "run" or len(words) < 6:
            continue
        minutes, end = _number(words[3]), _number(words[2])
        if not minutes or end is None or now - end > BATTERY_WINDOW:
            continue
        if out["blade_minutes"] is None or minutes > out["blade_minutes"]:
            out.update(blade_minutes=minutes, run_end=end, low_voltage=_number(words[5]))
    return out


def parse_battery_level(text: str) -> int | None:
    """MowBite's battery level from "<now> <t> <pct> <how>": a whole percentage worked out at most BATTERY_LEVEL_FRESH
    before, None without one ("<now> " none yet, "<now> <t> - off" a mower MowBite doesn't work it out for)"""
    words = text.split()
    if len(words) < 3 or not words[2].isdigit():
        return None
    now, t = _number(words[0]), _number(words[1])
    if now is None or t is None or now - t > BATTERY_LEVEL_FRESH:
        return None
    level = int(words[2])
    return level if level <= 100 else None


# what the card may read from the app for its dashboard, the way the app's own pages ask it: GET only, these paths
APP_READ = re.compile(
    r"^/(version\.json"
    r"|cgi-bin/(system|schedule|schedule\?log|stats|battery|battery\?level|version"
    r"|roslog\?(oldest|t=\d+&before=\d+&after=\d+)"
    r"|gpslog\?cells=\d+))$"
)


async def async_read(hass: HomeAssistant, url: str, path: str) -> tuple[int, str]:
    """One of APP_READ from the app at url, its status and text (502 when it doesn't answer)."""
    try:
        async with async_get_clientsession(hass).get(
            url.rstrip("/") + path, timeout=aiohttp.ClientTimeout(total=15)
        ) as response:
            return response.status, await response.text()
    except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError):
        return 502, ""


class AppStatus:
    """The app's status endpoints, read every minute (the slower ones less often), nothing without an address."""

    def __init__(self, hass: HomeAssistant, url: str | None, found: Callable[[list[str]], None]) -> None:
        self._hass = hass
        self._url = url.rstrip("/") if url else None
        # called with the endpoints that answered, they're features
        self._found = found
        self.version: str | None = None
        # the map's pictures the app serves (/mowbite-art.js): their interface version, and the file once asked. asked
        # again after each time the version was read (hourly): a version can be published again under its name
        self.art_api: int | None = None
        self._art: tuple[int, str] | None = None
        self._version_read = 0
        # the container's level (version.json), and MowBite's battery level while it has one
        self.level: int | None = None
        self.battery_level: int | None = None
        self.system: dict[str, Any] | None = None
        self.schedule: dict[str, Any] | None = None
        self.schedule_log: dict[str, Any] | None = None
        self.battery: dict[str, Any] | None = None
        self.stats: dict[str, Any] | None = None
        self._round = 0
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def async_start(self) -> Callable[[], None]:
        """Reads them soon and every minute, returns how to stop. Not waited for: five addresses that don't answer
        would hold up the start"""
        if not self._url:
            return lambda: None
        self._refresh(None)
        return async_track_time_interval(self._hass, self._refresh, STATUS_REFRESH)

    @callback
    def _refresh(self, _now: Any) -> None:
        self._hass.async_create_task(self.async_refresh(), eager_start=True)

    async def _get(self, path: str) -> str | None:
        try:
            async with async_get_clientsession(self._hass).get(
                f"{self._url}{path}", timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    return None
                return await response.text()
        except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError):
            return None

    async def async_art(self) -> tuple[int, str] | None:
        """The map's pictures the app serves and their interface version, asked once per reading of its version."""
        if not self._url:
            return None
        if self.version is None:
            # asked before the first refresh came back: the version now
            text = await self._get(VERSION_PATH)
            try:
                info = json.loads(text) if text else None
            except ValueError:
                info = None
            if isinstance(info, dict) and isinstance(info.get("version"), str):
                self._take_version(info)
        if self.art_api is None or self.version is None:
            return None
        if self._art is None or self._art[0] != self._version_read:
            text = await self._get(ART_PATH)
            if text is None or len(text) > ART_MAX:
                return None
            self._art = (self._version_read, text)
        return self.art_api, self._art[1]

    def _take_version(self, info: dict[str, Any]) -> None:
        """What version.json says: the version, the pictures' interface and the container's level."""
        self.version = info["version"]
        self._version_read += 1
        art, level = info.get("art"), info.get("level")
        self.art_api = art if isinstance(art, int) and not isinstance(art, bool) else None
        self.level = level if isinstance(level, int) and not isinstance(level, bool) else None

    async def async_refresh(self) -> None:
        found: list[str] = []
        n = self._round
        self._round += 1
        if n % VERSION_EVERY == 0 and (text := await self._get(VERSION_PATH)) is not None:
            try:
                info = json.loads(text)
            except ValueError:
                info = None
            if isinstance(info, dict) and isinstance(info.get("version"), str):
                self._take_version(info)
                found.append("version")
        system = parse_system(text) if (text := await self._get(SYSTEM_PATH)) is not None else {}
        # the computer's values are gone with it, the others keep what they said last
        self.system = system if "uptime" in system else None
        if self.system is not None:
            found.append("system")
            # the wifi only when the app runs on the mower
            if isinstance(system.get("wifi_signal"), float) and not system.get("remote"):
                found.append("wifi")
        if n % SCHEDULE_EVERY == 0:
            if (text := await self._get(SCHEDULE_PATH)) is not None and text.strip():
                self.schedule = parse_schedule(text)
                found.append("schedule")
            if (text := await self._get(SCHEDULE_LOG_PATH)) is not None:
                self.schedule_log = parse_schedule_log(text)
                found.append("schedule_log")
            if (text := await self._get(STATS_PATH)) is not None and (stats := parse_stats(text))["total"] is not None:
                self.stats = stats
                found.append("stats")
                found.extend(f"maint_{part}" for part in stats["parts"])
        level = None
        if (self.level or 0) >= BATTERY_LEVEL_FROM and (text := await self._get(BATTERY_LEVEL_PATH)) is not None:
            level = parse_battery_level(text)
        self.battery_level = level
        if n % BATTERY_EVERY == 0 and (text := await self._get(BATTERY_PATH)) is not None:
            battery = parse_battery(text, time.time())
            if battery["blade_minutes"] is not None:
                self.battery = battery
                found.append("battery")
        if found:
            self._found(found)
        for listener in list(self._listeners):
            listener()
