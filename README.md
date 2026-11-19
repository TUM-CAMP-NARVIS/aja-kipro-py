# aja-kipro

Control AJA Ki Pro recorders over their REST API from Python: start and stop recording, pick the storage
destination (USB or an SMB share) and directory per recording, name the clips, read the state, media and alarms.
Standard library only; Python 3.10 or newer.

Tested on a **Ki Pro GO** (firmware 5.0.0.16). The **Ki Pro Ultra 12G** (one channel, `eParamID_CustomClipName`)
follows AJA's reference but has not been tried on a device yet.

```bash
pip install "aja-kipro @ git+https://github.com/TUM-CAMP-NARVIS/aja-kipro-py@v0.1.0"
```

## Python

```python
from aja_kipro import KiPro, Destination

kp = KiPro("10.0.130.50")
kp.configure_recording(Destination.SMB, path="study/pilot-2026-11-19", clip_name="pilot-2026-11-19")
kp.record()          # returns when the device reports Recording (StateTimeout otherwise, with the raised alarms)
...
kp.stop()            # returns when the device is idle
print(kp.status(alarms=True).to_json())
```

`configure_recording` refuses a device that is not idle (`Busy`), then:

1. switches to Record-Play mode. The GO goes back to Data-LAN by itself after a recording, so call this before
   each recording;
2. sets the directory: for SMB relative to the share configured on the device (`eParamID_SMBMedia_1_Mount`), for
   USB on the drive (e.g. `/AJA/pilot/`). The device creates missing directories;
3. sets each channel's record destination and clip name (by default the enabled channels);
4. waits until the destination is mounted.

On the GO the files are `<clip name>_ch<n>_<clip number>_<take>.mp4`, e.g. `pilot-2026-11-19_ch1_0100_0001.mp4`.
The clip number goes up by one per recording.

Errors are subclasses of `KiProError`: `Unreachable`, `UnknownParameter`, `Rejected` (the device kept another
value), `Busy`, `StateTimeout`.

## Command line

```bash
kipro 10.0.130.50 status [--json] [--alarms]
kipro 10.0.130.50 prepare --destination smb --path study/test-01 --clip test-01
kipro 10.0.130.50 record
kipro 10.0.130.50 stop
kipro 10.0.130.50 get eParamID_TransportState eParamID_MediaState
kipro 10.0.130.50 set eParamID_ClipNumber 1
kipro 10.0.130.50 watch eParamID_TransportState      # configuration events as they happen
kipro 10.0.130.50 params clip                        # parameter ids from the device's descriptors
```

## Behaviour of the GO (5.0.0.16), measured

| | |
|---|---|
| Record → state Recording | about 0.2 s |
| Stop while recording → Idle | about 0.2 s, one Stop |
| new SMB path | taken at once; the share stays mounted |
| during a recording | `eParamID_CurrentClip` stays empty; `eParamID_TransportTimecode` shows the timecode input (00:00:00:00 without one) |
| after a recording | `eParamID_MediaState` is back at Data - LAN |

## API notes

Every call is an HTTP GET on `http://<device>/config` with `action=get|set|connect|wait_for_config_events`; no
authentication. The descriptors of all parameters are at `/desc.json`. AJA's reference:
<https://gitlab.aja.com/pub/rest_api>. The parameter ids and enum values used here are in
`src/aja_kipro/params.py`. Alarms are base64 protobuf messages (see `alarms.py` for the decoded fields).

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
```

The tests use a simulated GO (`tests/fake_device.py`) built on the descriptors of a real one
(`tests/fixtures_kipro_go_desc.json`).

## License

Apache License 2.0. Developed at the Chair for Computer Aided Medical Procedures and Augmented Reality (CAMP),
Technical University of Munich. Not affiliated with AJA Video Systems.
