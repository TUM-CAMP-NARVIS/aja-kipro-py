"""Parameter ids and enum values of the Ki Pro REST API.

Values are as the devices report them in their descriptors (``http://<device>/desc.json``); checked on a Ki Pro GO
(firmware 5.0.0.16). Ki Pro Ultra 12G values come from AJA's REST API reference
(https://gitlab.aja.com/pub/rest_api) and are not verified on a device.
"""
from __future__ import annotations

from enum import IntEnum

# ---- transport ----
TRANSPORT_COMMAND = "eParamID_TransportCommand"
TRANSPORT_STATE = "eParamID_TransportState"
TRANSPORT_TIMECODE = "eParamID_TransportTimecode"
CURRENT_CLIP = "eParamID_CurrentClip"
CLIP_NUMBER = "eParamID_ClipNumber"


class TransportCommand(IntEnum):
    NONE = 0
    PLAY = 1
    RECORD = 3
    STOP = 4  # while playing, the first Stop pauses and a second one goes to idle
    FAST_FORWARD = 5
    FAST_REVERSE = 6
    STEP_FORWARD = 7
    STEP_REVERSE = 8
    NEXT_CLIP = 9
    PREVIOUS_CLIP = 10


class TransportState(IntEnum):
    UNINITIALIZED = 0
    IDLE = 1
    RECORDING = 2
    PLAYING_FORWARD = 3
    FORWARD_2X = 4
    PLAYING_REVERSE = 9
    REVERSE_2X = 10
    PAUSED = 15
    SHUTDOWN = 20


# ---- media mode: recording needs Record-Play; Data - LAN serves the media to the network ----
MEDIA_STATE = "eParamID_MediaState"


class MediaState(IntEnum):
    RECORD_PLAY = 0
    DATA_LAN = 1


# ---- identity ----
SYS_NAME = "eParamID_SysName"
SERIAL = "eParamID_FormattedSerialNumber"
FIRMWARE = "eParamID_CurrentlyRunningImageVersion"
RECORD_FORMAT = "eParamID_RecordFormat"

# ---- channels (Ki Pro GO: 4) ----
MAX_CHANNELS = 4


def channel_enable(ch: int) -> str:
    return f"eParamID_Ch{ch}Enable"


def channel_clipname(ch: int) -> str:
    return f"eParamID_Channel_{ch}_Clipname"


def channel_main_destination(ch: int) -> str:
    return f"eParamID_Channel_{ch}_Main_Record_Destination"


def channel_backup_destination(ch: int) -> str:
    return f"eParamID_Channel_{ch}_Backup_Record_Destination"


def channel_recording_failed_alarm(ch: int) -> str:
    return f"eParamID_Channel_{ch}_Recording_Failed_Alarm"


# ---- single clip name (Ki Pro Ultra 12G; also present on the GO, where the per-channel names are used) ----
CUSTOM_CLIP_NAME = "eParamID_CustomClipName"
USE_CUSTOM_CLIP_NAME = "eParamID_UseCustomClipName"

# ---- storage (Ki Pro GO) ----
USB_PORTS = 5


class Destination(IntEnum):
    """A channel's record destination (``eParamID_Channel_<n>_Main_Record_Destination``)."""
    NONE = 0  # backup destination only
    USB1 = 5
    USB2 = 6
    USB3 = 7
    USB4 = 8
    USB5 = 9
    SMB = 10

    @classmethod
    def parse(cls, text: str) -> "Destination":
        """``smb``, ``usb1`` … ``usb5`` (case-insensitive)."""
        t = text.strip().lower()
        if t == "smb":
            return cls.SMB
        if t.startswith("usb") and t[3:].isdigit() and 1 <= int(t[3:]) <= USB_PORTS:
            return cls(cls.USB1 + int(t[3:]) - 1)
        raise ValueError(f"unknown destination {text!r} (smb, usb1 … usb{USB_PORTS})")

    @property
    def label(self) -> str:
        return "smb" if self is Destination.SMB else f"usb{self - Destination.USB1 + 1}" if self.is_usb else "none"

    @property
    def is_usb(self) -> bool:
        return Destination.USB1 <= self <= Destination.USB5


SMB_PATH = "eParamID_SMBMedia_1_Path"  # relative to the share
SMB_MOUNT = "eParamID_SMBMedia_1_Mount"  # server/share
SMB_STATE = "eParamID_Media_SMB_1_State"
SMB_CAPACITY = "eParamID_Media_SMB_1_Capacity"
SMB_REMAINING = "eParamID_Media_SMB_1_Remaining_Capacity"
SMB_REMAINING_PERCENT = "eParamID_Media_SMB_1_Remaining_Percent"


class SmbState(IntEnum):
    MOUNTED = 3
    ERROR = 9  # every other value (0, 1, 2, 4, 5) reads "Unmounted"


def usb_path(port: int) -> str:
    return f"eParamID_USBMedia_{port}_Path"


def usb_state(port: int) -> str:
    return f"eParamID_Media_Slot_{port}_State"


def usb_capacity(port: int) -> str:
    return f"eParamID_Media_Slot_{port}_Capacity"


def usb_remaining(port: int) -> str:
    return f"eParamID_Media_Slot_{port}_Remaining_Capacity"


def usb_remaining_percent(port: int) -> str:
    return f"eParamID_Media_Slot_{port}_Remaining_Percent"


class SlotState(IntEnum):
    UNKNOWN = 0
    MOUNTING = 1
    MOUNTED_RO = 2
    MOUNTED_RW = 3
    UNMOUNTING = 4
    UNMOUNTED = 5
    ERROR = 9
