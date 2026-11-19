import pytest

from aja_kipro import Busy, Destination, KiPro, Rejected, StateTimeout, TransportState, UnknownParameter, Unreachable
from aja_kipro.alarms import decode_alarm
from aja_kipro.cli import main

from fake_device import ALARM_IDLE, ALARM_RAISED, FakeKiPro


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


@pytest.fixture
def dev():
    return FakeKiPro()


@pytest.fixture
def kp(dev):
    clock = Clock()
    return KiPro("kipro.test", opener=dev, clock=clock, sleep=clock.sleep)


def test_get_and_unknown(kp):
    v = kp.get("eParamID_TransportState")
    assert (v.value, v.name, v.as_int()) == ("1", "Idle", 1)
    with pytest.raises(UnknownParameter):
        kp.get("eParamID_NoSuchThing")


def test_set_checks_the_reply(kp, dev):
    assert kp.set("eParamID_ClipNumber", 7).value == "7"
    dev.values["eParamID_ClipNumber"] = "7"
    dev._write = lambda pid, v: None  # the device ignores the set
    with pytest.raises(Rejected):
        kp.set("eParamID_ClipNumber", 8)


def test_unreachable(kp, dev):
    dev.unreachable = True
    with pytest.raises(Unreachable):
        kp.state()


def test_status(kp):
    st = kp.status()
    assert st.state == "idle" and not st.recording
    assert st.channels == (1, 2)
    assert st.destinations == {1: "smb", 2: "smb"}
    assert st.media_mode == "data-lan"
    (m,) = st.media
    assert (m.destination, m.mounted, m.remaining_percent, m.path) == ("smb", True, 86, "old/path")
    assert st.to_json()["channels"] == [1, 2]


def test_configure_smb_switches_mode_sets_path_and_names_and_waits_for_mount(kp, dev):
    kp.configure_recording(Destination.SMB, clip_name="pilot-2026-11-19", path="/ksv1/pilot-2026-11-19/")
    assert dev.values["eParamID_MediaState"] == "0"
    assert dev.values["eParamID_SMBMedia_1_Path"] == "ksv1/pilot-2026-11-19"
    assert dev.values["eParamID_Channel_1_Clipname"] == dev.values["eParamID_Channel_2_Clipname"] == "pilot-2026-11-19"
    assert dev.values["eParamID_Channel_3_Clipname"] == "Clip3"  # disabled channel untouched
    assert dev.values["eParamID_Media_SMB_1_State"] == "3"  # remounted (the fake hid it for a few reads)


def test_configure_usb(kp, dev):
    dev.values["eParamID_Media_Slot_2_State"] = "3"
    kp.configure_recording(Destination.USB2, clip_name="s1", path="AJA/s1", channels=[1])
    assert dev.values["eParamID_USBMedia_2_Path"] == "/AJA/s1/"
    assert dev.values["eParamID_Channel_1_Main_Record_Destination"] == "6"
    assert dev.values["eParamID_Channel_2_Main_Record_Destination"] == "10"


def test_configure_times_out_when_media_missing(kp):
    with pytest.raises(StateTimeout, match="usb3 mounted"):
        kp.configure_recording(Destination.USB3, clip_name="s1", mount_timeout=2)


@pytest.mark.parametrize("bad", [{"clip_name": "a b"}, {"clip_name": "x" * 65}, {"clip_name": "ok", "path": "../etc"},
                                 {"clip_name": "ok", "path": "a;b"}])
def test_configure_validates(kp, bad):
    with pytest.raises(ValueError):
        kp.configure_recording(Destination.SMB, **bad)


def test_configure_refused_while_recording(kp, dev):
    dev.values["eParamID_TransportState"] = "2"
    with pytest.raises(Busy):
        kp.configure_recording(Destination.SMB, clip_name="s1")


def test_record_and_stop(kp, dev):
    kp.configure_recording(Destination.SMB, clip_name="s1")
    kp.record()
    assert kp.state() is TransportState.RECORDING
    kp.record()  # already recording: no second command
    assert dev.sets.count(("eParamID_TransportCommand", "3")) == 1
    kp.stop()
    assert kp.state() is TransportState.IDLE
    kp.stop()  # idle: nothing sent
    assert dev.sets.count(("eParamID_TransportCommand", "4")) == 1


def test_stop_repeats_after_pause(kp, dev):
    dev.values["eParamID_TransportState"] = "15"  # paused (playback)
    kp.stop()
    assert kp.state() is TransportState.IDLE


def test_record_timeout_names_raised_alarms(kp, dev):
    dev.refuse_record = True
    dev.values["eParamID_MediaState"] = "0"
    dev.values["eParamID_Channel_1_Recording_Failed_Alarm"] = ALARM_RAISED
    with pytest.raises(StateTimeout, match="Fan Stopped"):
        kp.record(timeout=1)


def test_record_refused_while_playing(kp, dev):
    dev.values["eParamID_TransportState"] = "3"
    with pytest.raises(Busy):
        kp.record()


def test_alarm_decoding():
    a = decode_alarm("p", ALARM_RAISED)
    assert (a.raised, a.severity_name, a.text, a.short) == (True, "error", "Fan Stopped", "Fan Stopped")
    assert decode_alarm("p", ALARM_IDLE).raised is False
    assert decode_alarm("p", "") is None and decode_alarm("p", "!!notbase64") is None


def test_destination_parse():
    assert Destination.parse("SMB") is Destination.SMB
    assert Destination.parse("usb5") is Destination.USB5 and Destination.USB5.label == "usb5"
    for bad in ("usb0", "usb6", "nas"):
        with pytest.raises(ValueError):
            Destination.parse(bad)


def test_events_snapshot_then_changes(kp):
    ev = kp.events()
    first = next(ev)
    assert first["eParamID_TransportState"] == "1"
    assert next(ev) == {"eParamID_TransportState": "1"}


def test_cli(monkeypatch, capsys, dev):
    monkeypatch.setattr("aja_kipro.client.urllib.request.urlopen", dev)
    assert main(["kipro.test", "get", "eParamID_TransportState"]) == 0
    assert "eParamID_TransportState = 1 (Idle)" in capsys.readouterr().out
    assert main(["kipro.test", "status"]) == 0
    assert "1 -> smb, 2 -> smb" in capsys.readouterr().out
    assert main(["kipro.test", "get", "eParamID_Nope"]) == 1
    assert main(["kipro.test", "prepare", "--destination", "nas", "--clip", "x"]) == 2
