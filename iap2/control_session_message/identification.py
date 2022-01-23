from dataclasses import dataclass
from enum import IntEnum
from typing import List, Annotated

from iap2.control_session_message import csm, Uint16, Uint8, NoneLike


class PowerProvidingCapability(IntEnum):
    NONE = 0
    RESERVED = 1
    ADVANCED = 2


class MatchAction(IntEnum):
    NONE = 0
    SETTINGS_AND_PROMPT = 1
    SETTINGS_ONLY = 2


@dataclass
class ExternalAccessoryProtocol:
    id: Uint8 = None
    name: str = None
    match_action: MatchAction = None
    native_transport_component_identifier: Uint16 = None


@dataclass
class TransportComponent:
    id: Uint16 = None
    name: str = None
    supports_iap2_connection: NoneLike = None


@dataclass
class SerialTransportComponent(TransportComponent):
    pass


@dataclass
class BluetoothTransportComponent(TransportComponent):
    bluetooth_transport_mac: Annotated[bytes, 3] = None


@dataclass
class USBDeviceTransportComponent(TransportComponent):
    audio_sample_rate: Annotated[Uint8, 3] = None  # Fixme


@dataclass
class WirelessCarPlayTransportComponent(TransportComponent):
    supports_car_play: NoneLike = None


@dataclass
class USBHostTransportComponent(TransportComponent):
    car_play_interface_number: Annotated[Uint8, 3] = None


class EngineType(IntEnum):
    GAS = 0
    DIESEL = 1
    ELECTRIC = 2
    CNG = 3


@dataclass
class VehicleInformationComponent:
    id: Uint16
    name: str
    engine_type: EngineType


@dataclass
class VehicleStatusComponent:
    id: Uint16 = None
    name: str = None
    range: Annotated[NoneLike, 3] = None
    outside_temperature: Annotated[NoneLike, 4] = None
    range_warning: Annotated[NoneLike, 5] = None


@csm(0x1D00)
class StartIdentification:
    pass


@csm(0x1D01)
@dataclass
class IdentificationInformation:
    name: str = None
    model_identifier: str = None
    manufacturer: str = None
    serial_number: str = None
    fireware_version: str = None
    hardware_version: str = None
    messages_sent_by_accessory: bytes = None
    messages_received_from_accessory: bytes = None
    power_providing_capability: PowerProvidingCapability = None
    maximum_current_drawn_from_device: Uint16 = None
    supported_external_accessory_protocol: List[ExternalAccessoryProtocol] = None
    app_match_team_id: str = None
    current_language: str = None
    supported_language: List[str] = None
    serial_transport_component: List[SerialTransportComponent] = None
    usb_device_transport_component: List[USBDeviceTransportComponent] = None
    usb_host_transport_component: List[USBHostTransportComponent] = None
    bluetooth_transport_component: List[BluetoothTransportComponent] = None
    vehicle_information_component: Annotated[VehicleInformationComponent, 20] = None
    vehicle_status_component: Annotated[VehicleStatusComponent, 21] = None
    wireless_car_play_transport_component: Annotated[WirelessCarPlayTransportComponent, 24] = None


@csm(0x1D02)
class IdentificationAccepted:
    pass


@csm(0x1D03)
class IdentificationRejected:
    pass
