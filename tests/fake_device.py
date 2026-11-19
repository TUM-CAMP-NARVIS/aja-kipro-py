"""A simulated Ki Pro GO behind the client's ``opener``: the real descriptors (tests/fixtures_kipro_go_desc.json), a
parameter store with the values of an idle device, and the transport and media behaviour seen on a device:
Record reaches Recording after ``record_delay`` state reads, Stop goes back to Idle, a new SMB path unmounts the
share for ``remount_reads`` state reads."""
from __future__ import annotations

import io
import json
import urllib.parse
from pathlib import Path

DESC = json.loads((Path(__file__).parent / "fixtures_kipro_go_desc.json").read_text())

ALARM_IDLE = "CAAQABocCgxObyBDbGlwIE5hbWUSDE5vIENsaXAgTmFtZQ=="  # No Clip Name, not raised
ALARM_RAISED = "CAEQAhoaCgtGYW4gU3RvcHBlZBILRmFuIFN0b3BwZWQ="  # Fan Stopped, raised, error


class FakeKiPro:
    def __init__(self, *, record_delay: int = 2, remount_reads: int = 2, refuse_record: bool = False):
        self.known = {d["param_id"]: d for d in DESC}
        self.values: dict[str, str] = {
            "eParamID_SysName": "AJA Ki Pro GO", "eParamID_FormattedSerialNumber": "4KG000000",
            "eParamID_CurrentlyRunningImageVersion": "5.0.0.16-266r", "eParamID_TransportState": "1",
            "eParamID_TransportCommand": "4", "eParamID_MediaState": "1", "eParamID_CurrentClip": "",
            "eParamID_TransportTimecode": "00:00:00:00", "eParamID_ClipNumber": "100",
            "eParamID_Ch1Enable": "1", "eParamID_Ch2Enable": "1", "eParamID_Ch3Enable": "0", "eParamID_Ch4Enable": "0",
            "eParamID_Media_SMB_1_State": "3", "eParamID_SMBMedia_1_Path": "old/path",
            "eParamID_Media_SMB_1_Capacity": "1000", "eParamID_Media_SMB_1_Remaining_Capacity": "860",
            "eParamID_Media_SMB_1_Remaining_Percent": "86", "eParamID_CustomClipName": "x", "eParamID_UseCustomClipName": "0",
        }
        for c in range(1, 5):
            self.values[f"eParamID_Channel_{c}_Clipname"] = f"Clip{c}"
            self.values[f"eParamID_Channel_{c}_Main_Record_Destination"] = "10"
            self.values[f"eParamID_Channel_{c}_Recording_Failed_Alarm"] = ALARM_IDLE
        for n in range(1, 6):
            self.values[f"eParamID_USBMedia_{n}_Path"] = "/AJA/"
            self.values[f"eParamID_Media_Slot_{n}_State"] = "0"
            for k in ("Capacity", "Remaining_Capacity", "Remaining_Percent"):
                self.values[f"eParamID_Media_Slot_{n}_{k}"] = "0"
        self.record_delay, self.remount_reads, self.refuse_record = record_delay, remount_reads, refuse_record
        self._pending: tuple[str, int] | None = None  # (target state, reads left)
        self._unmounted_reads = 0
        self.sets: list[tuple[str, str]] = []
        self.requests: list[str] = []
        self.unreachable = False
        self._cid = 0

    # the client's opener
    def __call__(self, url: str, timeout: float = 0) -> io.BytesIO:
        if self.unreachable:
            raise OSError("no route to host")
        self.requests.append(url)
        u = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
        if u.path == "/desc.json":
            return _body(DESC)
        action, pid = q.get("action"), q.get("paramid", "")
        if action == "connect":
            self._cid += 1
            return _body({"connectionid": str(self._cid), "configevents": [dict(self.values)]})
        if action == "wait_for_config_events":
            return _body([{"param_id": "eParamID_TransportState", "value": self.values["eParamID_TransportState"]}])
        if pid not in self.known:
            return _body({})
        if action == "get":
            return _body(self._reply(pid, self._read(pid)))
        if action == "set":
            v = q.get("value", "")
            self.sets.append((pid, v))
            self._write(pid, v)
            return _body(self._reply(pid, self.values.get(pid, v)))
        return _body({})

    def _read(self, pid: str) -> str:
        if pid == "eParamID_TransportState" and self._pending:
            target, left = self._pending
            if left <= 0:
                self.values[pid] = target
                self._pending = None
            else:
                self._pending = (target, left - 1)
        if pid == "eParamID_Media_SMB_1_State" and self._unmounted_reads > 0:
            self._unmounted_reads -= 1
            return "0"
        return self.values.get(pid, "0")

    def _write(self, pid: str, v: str) -> None:
        if pid == "eParamID_TransportCommand":
            st = self.values["eParamID_TransportState"]
            if v == "3" and st == "1" and self.values["eParamID_MediaState"] == "0" and not self.refuse_record:
                self._pending = ("2", self.record_delay)
            elif v == "4" and st in ("2", "15"):
                self._pending = ("1", 1)
            return
        self.values[pid] = v
        if pid == "eParamID_SMBMedia_1_Path":
            self._unmounted_reads = self.remount_reads

    def _reply(self, pid: str, value: str) -> dict:
        names = {str(e["value"]): e.get("text", "") for e in self.known[pid].get("enum_values") or []}
        return {"paramid": "1", "name": pid, "value": value, "value_name": names.get(value, "")}


def _body(obj: object) -> io.BytesIO:
    return io.BytesIO(json.dumps(obj).encode())
