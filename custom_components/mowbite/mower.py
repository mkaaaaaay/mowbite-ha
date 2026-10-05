"""The connection to one OpenMower over its MQTT broker."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
import json
import logging
import math
import time
from typing import Any
import uuid

import aiomqtt

_LOGGER = logging.getLogger(__name__)

# what xbot_monitoring publishes, behind the prefix the mower was set up with
TOPIC_STATE = "robot_state/json"
TOPIC_ACTIONS = "actions/json"
TOPIC_SENSOR_INFOS = "sensor_infos/json"
TOPIC_SENSORS = "sensors/+/data"
TOPIC_EVENTS = "events/json"
TOPIC_POSITION = "position/json"
TOPIC_MAP = "map/json"
TOPIC_ACTION = "action"
TOPIC_RPC_REQUEST = "rpc/request"
# answers and errors both come here, told apart by "error"
TOPIC_RPC_RESPONSE = "rpc/response"

ACTION_START = "mower_logic:idle/start_mowing"
ACTION_PAUSE = "mower_logic:mowing/pause"
ACTION_CONTINUE = "mower_logic:mowing/continue"
ACTION_HOME = "mower_logic:mowing/abort_mowing"
ACTION_SKIP_AREA = "mower_logic:mowing/skip_area"
ACTION_RESET_EMERGENCY = "mower_logic/reset_emergency"
# drops an interrupted job, only there while idle with one (needs an OpenMower that has it)
ACTION_RESET_JOB = "mower_logic:idle/reset_job"

# keys listeners can ask for, sensors are "sensor:<id>"
KEY_STATE = "state"
KEY_ACTIONS = "actions"

# robot_state comes about once a second while ros runs, this long without it the mower counts as gone
# even if the broker is still there
STALE_AFTER = 30
RECONNECT_MIN = 5
RECONNECT_MAX = 60

# connack codes for a wrong login, mqtt 3.1.1 and 5
_AUTH_CODES = {4, 5, 134, 135}

RPC_TIMEOUT = 20


class CannotConnect(Exception):
    """The broker can't be reached."""


class InvalidAuth(Exception):
    """The broker turned the login down."""


class NoMower(Exception):
    """The broker is there but no mower publishes behind that prefix."""


class RpcError(Exception):
    """The mower answered an rpc with an error, or doesn't know the method."""


class Track:
    """Where the mower drove in the current job, with whether the blades were on.

    the same as the MowBite app keeps it: emptied when a new job starts, kept after the job until the next one
    """

    MAX_POINTS = 30000
    # closer than this to the last point is no new point, unless the blades went on or off
    STEP = 0.05

    def __init__(self) -> None:
        self.job_id: str | None = None
        self.points: list[tuple[float, float, bool]] = []
        # goes up whenever points are dropped or replaced, then the card needs all of them again
        self.generation = 0

    def add(self, x: float, y: float, blades: bool, job_id: str) -> bool:
        """A pose from position/json, True when it's a new point."""
        if not job_id:
            return False
        if job_id != self.job_id:
            self.job_id = job_id
            self.points = []
            self.generation += 1
        if self.points:
            lx, ly, lb = self.points[-1]
            if lb == blades and math.hypot(x - lx, y - ly) < self.STEP:
                return False
        self.points.append((round(x, 2), round(y, 2), blades))
        if len(self.points) > self.MAX_POINTS:
            self.points = self.points[-self.MAX_POINTS // 2 :]
            self.generation += 1
        return True

    def seed(self, job_id: str, recorded: list[tuple[float, float, bool]]) -> None:
        """What the mower recorded of the job before Home Assistant was there, in front of what came since."""
        if job_id != self.job_id or not recorded:
            return
        self.points = [(round(x, 2), round(y, 2), b) for x, y, b in recorded][-self.MAX_POINTS :] + self.points
        self.points = self.points[-self.MAX_POINTS :]
        self.generation += 1


def _history(result: Any) -> list[tuple[float, float, bool]]:
    """position.history's answer as points: the recorded segments, then what's still in its buffer."""
    points: list[tuple[float, float, bool]] = []
    if not isinstance(result, dict):
        return points
    blades = False
    for segment in result.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        blades = bool((segment.get("attributes") or {}).get("blades"))
        points.extend((p[0], p[1], blades) for p in segment.get("points") or [] if isinstance(p, list) and len(p) >= 2)
    points.extend((p[0], p[1], blades) for p in result.get("buffer") or [] if isinstance(p, list) and len(p) >= 2)
    return points


def normalize_prefix(prefix: str | None) -> str:
    """The prefix as it goes in front of a topic: empty, or ending with a slash."""
    prefix = (prefix or "").strip()
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return prefix


def _json(payload: bytes | bytearray | str) -> Any:
    try:
        return json.loads(payload)
    except ValueError:
        return None


def _value(payload: bytes | bytearray | str) -> float | str:
    text = payload.decode(errors="replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
    try:
        return float(text)
    except ValueError:
        return text.strip()


def _client(host: str, port: int, username: str | None, password: str | None, timeout: float) -> aiomqtt.Client:
    return aiomqtt.Client(
        host,
        port,
        username=username or None,
        password=password or None,
        timeout=timeout,
    )


async def async_probe(
    host: str, port: int, username: str | None, password: str | None, prefix: str, timeout: float = 15
) -> None:
    """Connect once and wait for robot_state, raises when that doesn't work."""
    prefix = normalize_prefix(prefix)
    connected = False
    try:
        async with asyncio.timeout(timeout):
            async with _client(host, port, username, password, timeout) as client:
                connected = True
                await client.subscribe(prefix + TOPIC_STATE)
                async for message in client.messages:
                    if isinstance(_json(message.payload), dict):
                        return
    except aiomqtt.MqttCodeError as err:
        code = getattr(err.rc, "value", err.rc)
        if code in _AUTH_CODES:
            raise InvalidAuth from err
        raise CannotConnect from err
    except aiomqtt.MqttError as err:
        raise CannotConnect from err
    except TimeoutError as err:
        raise (NoMower if connected else CannotConnect) from err


class Mower:
    """Keeps what the mower last said and sends it actions."""

    def __init__(self, host: str, port: int, username: str | None, password: str | None, prefix: str) -> None:
        self.host = host
        self._port = port
        self._username = username
        self._password = password
        self._prefix = normalize_prefix(prefix)
        self._client: aiomqtt.Client | None = None
        self._connected = False
        self._state_at = 0.0
        self._was_available = False
        self.closed = False
        self.state: dict[str, Any] | None = None
        # when robot_state last came, unix seconds
        self.state_time: float | None = None
        # action id -> enabled, None until actions/json came
        self.actions: dict[str, bool] | None = None
        self.sensors: dict[str, float | str] = {}
        # what xbot_monitoring says about each sensor: name, kind, limits
        self.sensor_infos: dict[str, dict[str, Any]] = {}
        # the newest STATE event (since when the state holds) and the area being mowed, from the events
        self.last_state_event: dict[str, Any] | None = None
        self.area: str | None = None
        # where the mower is, from position/json: x, y, heading and its job and blades
        self.position: dict[str, Any] | None = None
        self.map: dict[str, Any] | None = None
        self.map_version = 0
        self.track = Track()
        self._rpc: dict[str, asyncio.Future[Any]] = {}
        self._seeding: asyncio.Task[None] | None = None
        self._seeded: str | None = None
        self._listeners: dict[str, list[Callable[[], None]]] = {}
        self._event_listeners: list[Callable[[dict[str, Any]], None]] = []
        # called on anything the mower says, for the card
        self._change_listeners: list[Callable[[], None]] = []
        # the same event twice (a second subscription, a broker resending) would be a second push
        self._seen: deque[str] = deque(maxlen=200)

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def available(self) -> bool:
        return (
            self._connected
            and self.state is not None
            and time.monotonic() - self._state_at < STALE_AFTER
        )

    def add_listener(self, key: str, listener: Callable[[], None]) -> Callable[[], None]:
        """Called when that key changes or the mower comes or goes, returns how to stop it."""
        self._listeners.setdefault(key, []).append(listener)
        return lambda: self._listeners[key].remove(listener)

    def add_event_listener(self, listener: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        """Called once with each new event, in the order they came."""
        self._event_listeners.append(listener)
        return lambda: self._event_listeners.remove(listener)

    def add_change_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Called whenever anything changes, the mower comes or goes or the entry is unloaded."""
        self._change_listeners.append(listener)
        return lambda: self._change_listeners.remove(listener)

    def close(self) -> None:
        """The entry is going away, whoever still listens has to look for the new one."""
        self.closed = True
        if self._seeding is not None:
            self._seeding.cancel()
        self._changed()

    def action_enabled(self, action_id: str) -> bool | None:
        """Whether the mower offers that action right now, None while that isn't known yet."""
        if self.actions is None:
            return None
        return self.actions.get(action_id, False)

    async def async_action(self, action_id: str) -> None:
        if self._client is None or not self._connected:
            raise CannotConnect
        # so it can be told later what Home Assistant sent, MQTT doesn't say who sent an action
        _LOGGER.info("Sending %s to %s", action_id, self.host)
        await self._client.publish(self._prefix + TOPIC_ACTION, action_id)

    async def async_rpc(self, method: str, params: Any = None, timeout: float = RPC_TIMEOUT) -> Any:
        """Asks the mower over rpc/request, raises RpcError, CannotConnect or TimeoutError."""
        if self._client is None or not self._connected:
            raise CannotConnect
        request_id = uuid.uuid4().hex
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._rpc[request_id] = future
        try:
            payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}
            await self._client.publish(self._prefix + TOPIC_RPC_REQUEST, json.dumps(payload))
            async with asyncio.timeout(timeout):
                return await future
        finally:
            self._rpc.pop(request_id, None)

    def _seed(self, job_id: str) -> None:
        """The track of a job that was running before Home Assistant came, once per job (OpenMower 1.3 and newer)."""
        self._seeded = job_id
        if self._seeding is not None and not self._seeding.done():
            self._seeding.cancel()

        async def seed() -> None:
            try:
                result = await self.async_rpc("position.history", {"job_id": job_id})
            except (RpcError, CannotConnect, TimeoutError, aiomqtt.MqttError) as err:
                _LOGGER.debug("No track history for job %s: %s", job_id, err)
                return
            self.track.seed(job_id, _history(result))
            self._changed()

        try:
            self._seeding = asyncio.get_running_loop().create_task(seed())
        except RuntimeError:
            # no event loop (handled outside of one, in a test): nothing to ask
            self._seeding = None

    def check(self) -> None:
        """Tells everyone when the mower went quiet, robot_state stopping doesn't do that on its own."""
        if self.available != self._was_available:
            self._notify_all()

    async def run(self) -> None:
        """Stays connected until cancelled."""
        delay = RECONNECT_MIN
        while True:
            try:
                async with _client(self.host, self._port, self._username, self._password, 10) as client:
                    for topic in (
                        TOPIC_STATE,
                        TOPIC_ACTIONS,
                        TOPIC_SENSOR_INFOS,
                        TOPIC_SENSORS,
                        TOPIC_EVENTS,
                        TOPIC_POSITION,
                        TOPIC_MAP,
                        TOPIC_RPC_RESPONSE,
                    ):
                        await client.subscribe(self._prefix + topic)
                    self._client = client
                    self._connected = True
                    self._notify_all()
                    delay = RECONNECT_MIN
                    _LOGGER.debug("Connected to %s", self.host)
                    async for message in client.messages:
                        self.handle(str(message.topic), message.payload)
            except aiomqtt.MqttError as err:
                if self._connected:
                    _LOGGER.info("Lost the connection to %s: %s", self.host, err)
                else:
                    _LOGGER.debug("Can't connect to %s: %s", self.host, err)
            finally:
                was = self._connected
                self._client = None
                self._connected = False
                for future in self._rpc.values():
                    if not future.done():
                        future.set_exception(CannotConnect())
                if was:
                    self._notify_all()
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX)

    def handle(self, topic: str, payload: bytes | bytearray | str) -> None:
        """One message from the broker."""
        if not topic.startswith(self._prefix):
            return
        topic = topic[len(self._prefix) :]
        if topic == TOPIC_STATE:
            data = _json(payload)
            if not isinstance(data, dict):
                return
            before = self.state
            self.state = data
            self._state_at = time.monotonic()
            self.state_time = time.time()
            # an emergency stop comes as an EMERGENCY event only for mower_logic's own reasons, the stop button, a
            # lift or a bumper only show in robot_state. so robot_state is where an emergency starts and ends
            if before is not None and bool(before.get("emergency")) != bool(data.get("emergency")):
                self._event({"type": "EMERGENCY", "emergency": bool(data.get("emergency")), "t": self.state_time,
                             "source": "robot_state"})
            if not self._was_available:
                self._notify_all()
            else:
                self._notify(KEY_STATE)
        elif topic == TOPIC_ACTIONS:
            data = _json(payload)
            if not isinstance(data, list):
                return
            self.actions = {
                a["action_id"]: bool(a.get("enabled"))
                for a in data
                if isinstance(a, dict) and isinstance(a.get("action_id"), str)
            }
            self._notify(KEY_ACTIONS)
        elif topic == TOPIC_SENSOR_INFOS:
            data = _json(payload)
            if not isinstance(data, list):
                return
            self.sensor_infos = {
                i["sensor_id"]: i for i in data if isinstance(i, dict) and isinstance(i.get("sensor_id"), str)
            }
            self._changed()
        elif topic == TOPIC_EVENTS:
            data = _json(payload)
            for event in data if isinstance(data, list) else [data]:
                if isinstance(event, dict):
                    self._event(event)
        elif topic == TOPIC_POSITION:
            data = _json(payload)
            if not isinstance(data, dict) or not isinstance(data.get("x"), (int, float)):
                return
            attributes = data.get("attributes") or {}
            job_id = attributes.get("job_id") or ""
            self.position = {
                "x": data["x"],
                "y": data.get("y", 0),
                "heading": data.get("heading", 0),
                "blades": bool(attributes.get("blades")),
                "job_id": job_id,
            }
            self.track.add(data["x"], data.get("y", 0), bool(attributes.get("blades")), job_id)
            if job_id and job_id != self._seeded:
                self._seed(job_id)
            self._changed()
        elif topic == TOPIC_MAP:
            data = _json(payload)
            if isinstance(data, dict) and isinstance(data.get("areas"), list):
                self.map = data
                self.map_version += 1
                self._changed()
        elif topic == TOPIC_RPC_RESPONSE:
            data = _json(payload)
            if not isinstance(data, dict):
                return
            future = self._rpc.get(str(data.get("id")))
            if future is None or future.done():
                return
            if data.get("error") is not None:
                future.set_exception(RpcError(str(data["error"])))
            else:
                future.set_result(data.get("result"))
        elif topic.startswith("sensors/") and topic.endswith("/data"):
            sensor_id = topic[len("sensors/") : -len("/data")]
            self.sensors[sensor_id] = _value(payload)
            self._notify(f"sensor:{sensor_id}")

    def _event(self, event: dict[str, Any]) -> None:
        if not isinstance(event.get("type"), str):
            return
        # the ones from events/json would be a second message for the same emergency stop, robot_state tells it
        if event["type"] == "EMERGENCY" and event.get("source") != "robot_state":
            return
        event_id = event.get("id")
        if isinstance(event_id, str):
            if event_id in self._seen:
                return
            self._seen.append(event_id)
        if event["type"] == "STATE":
            self.last_state_event = event
            if event.get("state") != "MOWING":
                self.area = None
        elif event["type"] == "AREA":
            self.area = event.get("area_name") or None
        for listener in list(self._event_listeners):
            listener(event)
        self._changed()

    def _notify(self, key: str) -> None:
        for listener in list(self._listeners.get(key, ())):
            listener()
        self._changed()

    def _notify_all(self) -> None:
        self._was_available = self.available
        for listeners in list(self._listeners.values()):
            for listener in list(listeners):
                listener()
        self._changed()

    def _changed(self) -> None:
        for listener in list(self._change_listeners):
            listener()
