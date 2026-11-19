"""``kipro``: the Ki Pro REST API from the command line.

    kipro 10.0.130.50 status [--json] [--alarms]
    kipro 10.0.130.50 get eParamID_TransportState [...]
    kipro 10.0.130.50 set eParamID_ClipNumber 1
    kipro 10.0.130.50 prepare --destination smb --path ksv1/test-01 --clip test-01
    kipro 10.0.130.50 record | stop
    kipro 10.0.130.50 watch [eParamID_TransportState ...]
    kipro 10.0.130.50 params [substring]
The host may also come from KIPRO_HOST.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .client import KiPro, KiProError
from .params import Destination


def _print_status(kp: KiPro, as_json: bool, alarms: bool) -> None:
    st = kp.status(alarms=alarms)
    if as_json:
        print(json.dumps(st.to_json(), indent=2))
        return
    print(f"{st.name} (serial {st.serial}, firmware {st.firmware})")
    print(f"  state      {st.state}{'  clip ' + st.clip if st.clip else ''}  tc {st.timecode}")
    print(f"  media mode {st.media_mode}")
    chans = ", ".join(f"{c} -> {st.destinations.get(c, '?')}" for c in st.channels) or "none"
    print(f"  channels   {chans}")
    for m in st.media:
        pct = f"{m.remaining_percent}% free" if m.remaining_percent is not None else ""
        print(f"  {m.destination:<10} {'mounted' if m.mounted else m.state}  {pct}  path {m.path!r}")
    for a in st.alarms:
        print(f"  ALARM ({a.severity_name}) {a.text}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kipro", description="Control an AJA Ki Pro over its REST API.")
    ap.add_argument("--version", action="version", version=f"aja-kipro {__version__}")
    ap.add_argument("host", nargs="?", default=os.environ.get("KIPRO_HOST"), help="device address (or KIPRO_HOST)")
    ap.add_argument("--timeout", type=float, default=5.0, help="per-request timeout in seconds")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="state, channels, media")
    s.add_argument("--json", action="store_true")
    s.add_argument("--alarms", action="store_true", help="also the raised alarms")
    g = sub.add_parser("get", help="read parameters")
    g.add_argument("params", nargs="+")
    t = sub.add_parser("set", help="set a parameter")
    t.add_argument("param")
    t.add_argument("value")
    p = sub.add_parser("prepare", help="destination, directory and clip name of the next recording")
    p.add_argument("--destination", required=True, help="smb, usb1 … usb5")
    p.add_argument("--path", help="directory (SMB: relative to the share)")
    p.add_argument("--clip", required=True, help="clip name")
    p.add_argument("--channels", help="comma-separated channel numbers (default: the enabled ones)")
    r = sub.add_parser("record", help="start recording, wait for Recording")
    r.add_argument("--wait", type=float, default=15.0)
    o = sub.add_parser("stop", help="stop, wait for Idle")
    o.add_argument("--wait", type=float, default=15.0)
    w = sub.add_parser("watch", help="print configuration events")
    w.add_argument("params", nargs="*", help="only these parameters")
    d = sub.add_parser("params", help="list parameter ids from the descriptors")
    d.add_argument("filter", nargs="?", default="")
    a = ap.parse_args(argv)
    if not a.host:
        ap.error("no host (argument or KIPRO_HOST)")
    kp = KiPro(a.host, timeout=a.timeout)
    try:
        if a.cmd == "status":
            _print_status(kp, a.json, a.alarms)
        elif a.cmd == "get":
            for name in a.params:
                v = kp.get(name)
                print(f"{v.param} = {v.value}" + (f" ({v.name})" if v.name != v.value else ""))
        elif a.cmd == "set":
            v = kp.set(a.param, a.value, check=False)
            print(f"{a.param} = {v.value if v else a.value}" + (f" ({v.name})" if v and v.name != v.value else ""))
        elif a.cmd == "prepare":
            chans = [int(c) for c in a.channels.split(",")] if a.channels else None
            kp.configure_recording(Destination.parse(a.destination), clip_name=a.clip, path=a.path, channels=chans)
            _print_status(kp, False, False)
        elif a.cmd == "record":
            kp.record(timeout=a.wait)
            print("recording")
        elif a.cmd == "stop":
            kp.stop(timeout=a.wait)
            print("idle")
        elif a.cmd == "watch":
            only = set(a.params)
            for batch in kp.events():
                for k, v in batch.items():
                    if not only or k in only:
                        print(f"{k} = {v}", flush=True)
        elif a.cmd == "params":
            for desc in sorted(kp.descriptors(), key=lambda x: str(x.get("param_id"))):
                pid = str(desc.get("param_id"))
                if a.filter.lower() in pid.lower():
                    print(pid)
    except KiProError as e:
        print(f"kipro: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"kipro: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
