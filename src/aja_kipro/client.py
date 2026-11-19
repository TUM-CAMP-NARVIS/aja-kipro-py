"""Client of one Ki Pro's REST API (``http://<device>/config``): every call is an HTTP GET.

    kp = KiPro("10.0.130.50")
    kp.configure_recording(Destination.SMB, path="ksv1/pilot-2026-11-19", clip_name="pilot-2026-11-19")
    kp.record()     # returns once the device reports Recording
    ...
    kp.stop()       # returns once the device is idle

Only the standard library is used. One instance may be shared between threads (each call is its own request).
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field

from . import params as P
from .alarms import Alarm, decode_alarm
from .params import Destination, MediaState, SlotState, SmbState, TransportCommand, TransportState

DEFAULT_TIMEOUT_S = 5.0
POLL_S = 0.2
# Paths and clip names are sent to the device as given: keep them to a safe set (no "..", no control characters).
_PATH_RE = re.compile(r"^[A-Za-z0-9_\-. /]{1,200}$")
_CLIP_RE = re.compile(r"^[A-Za-z0-9_\-.]{1,64}$")


class KiProError(Exception):
    """Base class of the errors of this library."""


class Unreachable(KiProError):
    """The device did not answer (network error, HTTP error, timeout of one request)."""


class UnknownParameter(KiProError):
    """The device does not know the parameter (it answers ``{}``)."""


class Rejected(KiProError):
    """The device did not take a value (it reports another value after the set)."""


class Busy(KiProError):
    """The device is not idle (recording or playing) and cannot be reconfigured."""


class StateTimeout(KiProError):
    """The device did not reach the expected state in time."""


@dataclass(frozen=True)
class Value:
    param: str
    value: str
    name: str  # the enum's text, or the value again for other types

    def as_int(self) -> int:
        return int(self.value)


@dataclass(frozen=True)
class Media:
    destination: str  # "smb", "usb1" … "usb5"
    mounted: bool
    state: str
    capacity: int | None  # as the device reports it (the unit is not documented)
    remaining: int | None
    remaining_percent: int | None
    path: str


@dataclass(frozen=True)
class Status:
    name: str
    serial: str
    firmware: str
    state: str  # TransportState name, lower case, e.g. "idle", "recording"
    recording: bool
    media_mode: str  # "record-play" or "data-lan"
    clip: str
    timecode: str
    channels: tuple[int, ...]  # enabled channels
    destinations: dict[int, str]  # channel -> main record destination
    media: tuple[Media, ...]  # the destinations in use by the enabled channels
    alarms: tuple[Alarm, ...] = field(default=())  # raised alarms

    def to_json(self) -> dict:
        return {
            "name": self.name, "serial": self.serial, "firmware": self.firmware, "state": self.state,
            "recording": self.recording, "media_mode": self.media_mode, "clip": self.clip, "timecode": self.timecode,
            "channels": list(self.channels), "destinations": {str(k): v for k, v in self.destinations.items()},
            "media": [m.__dict__ for m in self.media],
            "alarms": [{"param": a.param, "severity": a.severity_name, "text": a.text, "short": a.short}
                       for a in self.alarms],
        }


class KiPro:
    def __init__(self, host: str, *, timeout: float = DEFAULT_TIMEOUT_S, port: int = 80,
                 opener: Callable[..., object] | None = None, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        if not host or "/" in host:
            raise ValueError(f"host must be an address or name, got {host!r}")
        self.host = host
        self.base = f"http://{host}" + ("" if port == 80 else f":{port}")
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen
        self._clock = clock
        self._sleep = sleep
        self._known: frozenset[str] | None = None

    # ---- low level ----
    def _request(self, path: str, query: dict[str, str], timeout: float | None = None) -> object:
        url = f"{self.base}{path}?{urllib.parse.urlencode(query)}" if query else f"{self.base}{path}"
        try:
            with self._open(url, timeout=timeout or self.timeout) as r:  # type: ignore[attr-defined]
                body = r.read()
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise Unreachable(f"{self.host}: {getattr(e, 'reason', e)}") from e
        try:
            return json.loads(body) if body.strip() else {}
        except ValueError as e:
            raise Unreachable(f"{self.host}: not JSON: {body[:80]!r}") from e

    def get(self, param: str) -> Value:
        r = self._request("/config", {"action": "get", "paramid": param})
        if not isinstance(r, dict) or "value" not in r:
            raise UnknownParameter(f"{self.host}: unknown parameter {param}")
        return Value(param, str(r["value"]), str(r.get("value_name") or r["value"]))

    def set(self, param: str, value: object, *, check: bool = True) -> Value | None:
        """Set ``param``. With ``check``, a reply that names another value raises Rejected (commands, whose value
        the device resets, are sent with check=False)."""
        text = str(int(value)) if isinstance(value, (bool, int)) else str(value)
        r = self._request("/config", {"action": "set", "paramid": param, "value": text})
        if isinstance(r, dict) and r and "value" not in r:
            raise UnknownParameter(f"{self.host}: unknown parameter {param}")
        if not isinstance(r, dict) or "value" not in r:
            return None
        got = Value(param, str(r["value"]), str(r.get("value_name") or r["value"]))
        if check and got.value != text:
            raise Rejected(f"{self.host}: {param} is {got.value!r} after setting {text!r}")
        return got

    def descriptors(self) -> list[dict]:
        """All parameter descriptors (``/desc.json``, about 200 kB)."""
        r = self._request("/desc.json", {}, timeout=max(self.timeout, 15.0))
        if not isinstance(r, list):
            raise Unreachable(f"{self.host}: /desc.json is not a list")
        return r

    def known(self, param: str) -> bool:
        """Whether the device has ``param`` (from its descriptors, fetched once)."""
        if self._known is None:
            self._known = frozenset(str(d.get("param_id")) for d in self.descriptors())
        return param in self._known

    def events(self, *, poll_timeout: float = 30.0) -> Iterator[dict[str, str]]:
        """The device's configuration events: first the full snapshot (``action=connect``), then each batch of
        changed parameters (``action=wait_for_config_events``), as {param: value}. Runs until the caller stops."""
        r = self._request("/config", {"action": "connect"})
        if not isinstance(r, dict) or "connectionid" not in r:
            raise Unreachable(f"{self.host}: connect did not return a connection id")
        cid = str(r["connectionid"])
        yield _merge(r.get("configevents") or [])
        while True:
            batch = self._request("/config", {"action": "wait_for_config_events", "connectionid": cid},
                                  timeout=poll_timeout)
            if isinstance(batch, list) and batch:
                yield _merge(batch)

    # ---- state ----
    def state(self) -> TransportState:
        v = self.get(P.TRANSPORT_STATE).as_int()
        try:
            return TransportState(v)
        except ValueError:
            return TransportState.UNINITIALIZED

    def wait_for(self, cond: Callable[[], bool], timeout: float, what: str) -> None:
        deadline = self._clock() + timeout
        while True:
            if cond():
                return
            if self._clock() >= deadline:
                raise StateTimeout(f"{self.host}: {what} not reached within {timeout:g} s")
            self._sleep(POLL_S)

    def channels(self) -> tuple[int, ...]:
        """The enabled channels (multi-channel models), or (1,) for a single-channel model."""
        if not self.known(P.channel_enable(1)):
            return (1,)
        return tuple(c for c in range(1, P.MAX_CHANNELS + 1)
                     if self.known(P.channel_enable(c)) and self.get(P.channel_enable(c)).value == "1")

    def snapshot(self) -> dict[str, str]:
        """Every parameter's value in one request (the snapshot of ``action=connect``)."""
        return next(self.events())

    def raised_alarms(self) -> tuple[Alarm, ...]:
        """The raised alarms, from one snapshot."""
        out = []
        for p, v in sorted(self.snapshot().items()):
            if p.endswith("_Alarm"):
                a = decode_alarm(p, v)
                if a is not None and a.raised:
                    out.append(a)
        return tuple(out)

    def media(self, dest: Destination) -> Media:
        if dest is Destination.SMB:
            st = self.get(P.SMB_STATE)
            return Media("smb", st.as_int() == SmbState.MOUNTED, st.name.lower(), _int(self, P.SMB_CAPACITY),
                         _int(self, P.SMB_REMAINING), _int(self, P.SMB_REMAINING_PERCENT), self.get(P.SMB_PATH).value)
        if dest.is_usb:
            n = dest - Destination.USB1 + 1
            st = self.get(P.usb_state(n))
            return Media(dest.label, st.as_int() == SlotState.MOUNTED_RW, st.name.lower(), _int(self, P.usb_capacity(n)),
                         _int(self, P.usb_remaining(n)), _int(self, P.usb_remaining_percent(n)),
                         self.get(P.usb_path(n)).value)
        raise ValueError(f"no media for destination {dest!r}")

    def status(self, *, alarms: bool = False) -> Status:
        """The device status; with ``alarms`` also the raised alarms (one more, larger request)."""
        st = self.state()
        chans = self.channels()
        dests: dict[int, str] = {}
        used: list[Destination] = []
        for c in chans:
            if self.known(P.channel_main_destination(c)):
                d = Destination(self.get(P.channel_main_destination(c)).as_int())
                dests[c] = d.label
                if d not in used:
                    used.append(d)
        media = tuple(self.media(d) for d in used if d is not Destination.NONE)
        mode = self.get(P.MEDIA_STATE).as_int() if self.known(P.MEDIA_STATE) else MediaState.RECORD_PLAY
        return Status(
            name=_str(self, P.SYS_NAME), serial=_str(self, P.SERIAL), firmware=_str(self, P.FIRMWARE),
            state=st.name.lower(), recording=st is TransportState.RECORDING,
            media_mode="record-play" if mode == MediaState.RECORD_PLAY else "data-lan",
            clip=_str(self, P.CURRENT_CLIP), timecode=_str(self, P.TRANSPORT_TIMECODE), channels=chans,
            destinations=dests, media=media, alarms=self.raised_alarms() if alarms else (),
        )

    # ---- recording ----
    def configure_recording(self, destination: Destination, *, clip_name: str, path: str | None = None,
                            channels: Sequence[int] | None = None, mount_timeout: float = 30.0) -> None:
        """Prepare the next recording: Record-Play mode, the destination (and its directory) for ``channels`` (by
        default the enabled ones) and the clip name, then wait until the destination is mounted writable.

        ``path``: for SMB the directory relative to the share (e.g. ``ksv1/pilot-2026-11-19``), for USB the directory
        on the drive (e.g. ``/AJA/pilot-2026-11-19/``); None keeps the device's. On a multi-channel model the
        device appends ``_ch<n>_<clip number>_<take>`` to the clip name of each channel."""
        if not _CLIP_RE.match(clip_name):
            raise ValueError(f"invalid clip name {clip_name!r} (letters, digits, _ - .; at most 64)")
        if path is not None and (not _PATH_RE.match(path) or ".." in path.split("/")):
            raise ValueError(f"invalid path {path!r}")
        st = self.state()
        if st not in (TransportState.IDLE, TransportState.UNINITIALIZED):
            raise Busy(f"{self.host}: device is {st.name.lower()}, not idle")
        chans = tuple(channels) if channels else self.channels()
        if not chans:
            raise KiProError(f"{self.host}: no channel enabled")
        if self.known(P.MEDIA_STATE) and self.get(P.MEDIA_STATE).as_int() != MediaState.RECORD_PLAY:
            self.set(P.MEDIA_STATE, int(MediaState.RECORD_PLAY))
        if path is not None:
            if destination is Destination.SMB:
                self.set(P.SMB_PATH, path.strip("/"))
            elif destination.is_usb:
                self.set(P.usb_path(destination - Destination.USB1 + 1), "/" + path.strip("/") + "/")
        multi = self.known(P.channel_clipname(1))
        for c in chans:
            if multi:
                self.set(P.channel_main_destination(c), int(destination))
                self.set(P.channel_clipname(c), clip_name)
        if not multi:
            self.set(P.CUSTOM_CLIP_NAME, clip_name)
            self.set(P.USE_CUSTOM_CLIP_NAME, 1)
        if multi:
            self.wait_for(lambda: self.media(destination).mounted, mount_timeout, f"{destination.label} mounted")

    def record(self, *, timeout: float = 15.0) -> None:
        """Start recording and wait until the device reports Recording (with its raised alarms if it does not)."""
        st = self.state()
        if st is TransportState.RECORDING:
            return
        if st not in (TransportState.IDLE, TransportState.UNINITIALIZED):
            raise Busy(f"{self.host}: device is {st.name.lower()}, not idle")
        self.set(P.TRANSPORT_COMMAND, int(TransportCommand.RECORD), check=False)
        try:
            self.wait_for(lambda: self.state() is TransportState.RECORDING, timeout, "recording")
        except StateTimeout as e:
            alarms = "; ".join(a.short for a in self.raised_alarms())
            raise StateTimeout(f"{e}{' (alarms: ' + alarms + ')' if alarms else ''}") from None

    def stop(self, *, timeout: float = 15.0) -> None:
        """Stop recording (or playback) and wait until the device is idle. When a Stop only pauses (playback), one
        more Stop is sent."""
        idle_states = (TransportState.IDLE, TransportState.UNINITIALIZED)
        st = self.state()
        if st in idle_states:
            return
        self.set(P.TRANSPORT_COMMAND, int(TransportCommand.STOP), check=False)
        again = st is not TransportState.PAUSED  # paused already: the Stop just sent is the second one

        def idle() -> bool:
            nonlocal again
            s = self.state()
            if s is TransportState.PAUSED and again:
                self.set(P.TRANSPORT_COMMAND, int(TransportCommand.STOP), check=False)
                again = False
            return s in idle_states

        self.wait_for(idle, timeout, "idle")


def _merge(batch: list) -> dict[str, str]:
    out: dict[str, str] = {}
    for e in batch:
        if isinstance(e, dict):
            if "param_id" in e and "value" in e:
                out[str(e["param_id"])] = str(e["value"])
            else:
                out.update({str(k): str(v) for k, v in e.items() if not isinstance(v, (list, dict))})
    return out


def _int(kp: KiPro, param: str) -> int | None:
    try:
        return kp.get(param).as_int()
    except (UnknownParameter, ValueError):
        return None


def _str(kp: KiPro, param: str) -> str:
    try:
        return kp.get(param).value
    except UnknownParameter:
        return ""
