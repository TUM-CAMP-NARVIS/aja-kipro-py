"""Ki Pro alarms: parameters of type ``data`` with class ``alarm``, whose value is a base64 protobuf message
(``/alarm.proto``, not published). Decoded fields, as observed on a Ki Pro GO:

- 1 (varint): the alarm is raised (non-zero) or not. Inferred: 0 on every alarm of an idle device;
- 2 (varint): severity, 0 info, 1 warning, 2 error (e.g. "Fan Stopped" is 2);
- 3 (message): 1 the long text, 2 the short text.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass


@dataclass(frozen=True)
class Alarm:
    param: str
    raised: bool
    severity: int  # 0 info, 1 warning, 2 error
    text: str
    short: str

    @property
    def severity_name(self) -> str:
        return {0: "info", 1: "warning", 2: "error"}.get(self.severity, f"severity {self.severity}")


def _varint(b: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        if i >= len(b):
            raise ValueError("truncated varint")
        x = b[i]
        i += 1
        result |= (x & 0x7F) << shift
        shift += 7
        if not x & 0x80:
            return result, i


def _fields(b: bytes) -> list[tuple[int, int | bytes]]:
    out: list[tuple[int, int | bytes]] = []
    i = 0
    while i < len(b):
        key, i = _varint(b, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            v, i = _varint(b, i)
            out.append((field, v))
        elif wire == 2:
            n, i = _varint(b, i)
            if i + n > len(b):
                raise ValueError("truncated field")
            out.append((field, b[i:i + n]))
            i += n
        else:
            raise ValueError(f"unsupported wire type {wire}")
    return out


def decode_alarm(param: str, value: str) -> Alarm | None:
    """The alarm in ``value`` (the parameter's base64 value), or None if it is empty or not decodable."""
    if not value:
        return None
    try:
        fields = _fields(base64.b64decode(value, validate=True))
    except (ValueError, binascii.Error):
        return None
    raised = severity = 0
    text = short = ""
    for f, v in fields:
        if f == 1 and isinstance(v, int):
            raised = v
        elif f == 2 and isinstance(v, int):
            severity = v
        elif f == 3 and isinstance(v, bytes):
            try:
                for g, w in _fields(v):
                    if isinstance(w, bytes):
                        if g == 1:
                            text = w.decode("utf-8", "replace")
                        elif g == 2:
                            short = w.decode("utf-8", "replace")
            except ValueError:
                pass
    return Alarm(param, bool(raised), severity, text, short or text)
