from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Annotated, Optional

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
    id: Uint8
    name: str
    match_action: MatchAction
    native_transport_component_identifier: Optional[Uint16] = None


@dataclass
class TransportComponent:
    id: Uint16
    name: str
    supports_iap2_connection: NoneLike = None


@dataclass
class SerialTransportComponent(TransportComponent):
    pass


@dataclass
class BluetoothTransportComponent(TransportComponent):
    bluetooth_transport_mac: Annotated[bytes, 3] = None


@dataclass
class USBDeviceTransportComponent(TransportComponent):
    audio_sample_rate: Annotated[Optional[Uint8], 3] = None  # Fixme


@dataclass
class WirelessCarPlayTransportComponent(TransportComponent):
    supports_car_play: Annotated[NoneLike, 4] = None


@dataclass
class USBHostTransportComponent(TransportComponent):
    car_play_interface_number: Annotated[Optional[Uint8], 3] = None


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
    id: Uint16
    name: str
    range: Annotated[NoneLike, 3] = None
    outside_temperature: Annotated[NoneLike, 4] = None
    range_warning: Annotated[NoneLike, 5] = None


@csm(0x1D00)
class StartIdentification:
    pass


@csm(0x1D01)
@dataclass
class IdentificationInformation:
    name: str
    model_identifier: str
    manufacturer: str
    serial_number: str
    fireware_version: str
    hardware_version: str
    messages_sent_by_accessory: bytes
    messages_received_from_accessory: bytes
    power_providing_capability: PowerProvidingCapability
    maximum_current_drawn_from_device: Uint16
    supported_external_accessory_protocol: List[ExternalAccessoryProtocol]
    app_match_team_id: Optional[str]
    current_language: str
    supported_language: List[str]
    serial_transport_component: List[SerialTransportComponent] = field(default_factory=list)
    usb_device_transport_component: List[USBDeviceTransportComponent] = field(default_factory=list)
    usb_host_transport_component: List[USBHostTransportComponent] = field(default_factory=list)
    bluetooth_transport_component: List[BluetoothTransportComponent] = field(default_factory=list)
    vehicle_information_component: Annotated[Optional[VehicleInformationComponent], 20] = None
    vehicle_status_component: Annotated[Optional[VehicleStatusComponent], 21] = None
    wireless_car_play_transport_component: Annotated[Optional[WirelessCarPlayTransportComponent], 24] = None


@csm(0x1D02)
class IdentificationAccepted:
    pass


@csm(0x1D03)
@dataclass
class IdentificationRejected:
    name: NoneLike
    model_identifier: NoneLike
    manufacturer: NoneLike
    serial_number: NoneLike
    fireware_version: NoneLike
    hardware_version: NoneLike
    messages_sent_by_accessory: NoneLike
    messages_received_from_accessory: NoneLike
    power_providing_capability: NoneLike
    maximum_current_drawn_from_device: NoneLike
    supported_external_accessory_protocol: NoneLike
    app_match_team_id: NoneLike
    current_language: NoneLike
    supported_language: NoneLike
    serial_transport_component: NoneLike
    usb_device_transport_component: NoneLike
    usb_host_transport_component: NoneLike
    bluetooth_transport_component: NoneLike
    vehicle_information_component: Annotated[NoneLike, 20]
    vehicle_status_component: Annotated[NoneLike, 21]
    wireless_car_play_transport_component: Annotated[NoneLike, 24]
