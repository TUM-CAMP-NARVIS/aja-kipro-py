"""Control AJA Ki Pro recorders (Ki Pro GO, Ki Pro Ultra 12G) over their REST API."""
from .alarms import Alarm, decode_alarm
from .client import (Busy, KiPro, KiProError, Media, Rejected, StateTimeout, Status, UnknownParameter, Unreachable,
                     Value)
from .params import Destination, MediaState, TransportCommand, TransportState

__version__ = "0.1.0"
__all__ = [
    "Alarm", "Busy", "Destination", "KiPro", "KiProError", "Media", "MediaState", "Rejected", "StateTimeout",
    "Status", "TransportCommand", "TransportState", "UnknownParameter", "Unreachable", "Value", "decode_alarm",
]
