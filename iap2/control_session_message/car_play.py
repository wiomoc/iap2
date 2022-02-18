from dataclasses import dataclass
from enum import IntEnum

from iap2.control_session_message import csm, Uint16, Uint8


@csm(0x4E0E)
@dataclass
class DeviceTransportIdentifierNotification:
    bluetooth_transport_id: str
    usb_transport_id: str


class WirelessCarPlayStatus(IntEnum):
    UNAVAILABLE = 0
    AVAILABLE = 1


@csm(0x4E0D)
@dataclass
class WirelessCarPlayUpdate:
    status: WirelessCarPlayStatus
