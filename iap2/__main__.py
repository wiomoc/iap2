import asyncio

from iap2.control_session_message import read_csm, register_csm, write_csm, Uint16, Uint8
from iap2.control_session_message.identification import IdentificationRejected, IdentificationAccepted, \
    StartIdentification, IdentificationInformation, PowerProvidingCapability, ExternalAccessoryProtocol, MatchAction, \
    BluetoothTransportComponent, VehicleInformationComponent, EngineType, VehicleStatusComponent, \
    WirelessCarPlayTransportComponent
from iap2.control_session_message.eap import StartExternalAccessoryProtocolSession, StopExternalAccessoryProtocolSession
from iap2.control_session_message.vehicle_status import StartVehicleStatusUpdates, StopVehicleStatusUpdates, \
    VehicleStatusUpdate
from iap2.mfi_auth_coprocessor import read_certificate, generate_challenge_response
from iap2.link_layer import IAP2Connection
from iap2.transport.bluetooth import BluetoothTransport
from iap2.control_session_message.authentication import RequestAuthenticationCertificate, AuthenticationCertificate, \
    RequestAuthenticationChallengeResponse, AuthenticationResponse, AuthenticationSucceeded, AuthenticationFailed

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    register_csm(RequestAuthenticationCertificate)
    register_csm(RequestAuthenticationChallengeResponse)
    register_csm(AuthenticationSucceeded)
    register_csm(AuthenticationFailed)

    register_csm(StartIdentification)
    register_csm(IdentificationAccepted)
    register_csm(IdentificationRejected)

    register_csm(StartVehicleStatusUpdates)
    register_csm(StopVehicleStatusUpdates)


    async def handle_auth(stream):
        while True:
            incoming_message = await read_csm(stream)
            print(incoming_message)
            if isinstance(incoming_message, RequestAuthenticationCertificate):
                cert = read_certificate()
                await write_csm(stream, AuthenticationCertificate(certificate=cert))
            elif isinstance(incoming_message, RequestAuthenticationChallengeResponse):
                response = generate_challenge_response(incoming_message.challenge)
                await write_csm(stream, AuthenticationResponse(response=response))
            elif isinstance(incoming_message, AuthenticationSucceeded):
                return
            else:
                raise Exception("auth failed")


    async def handle_identification(stream):
        def messages_ids(*messages):
            from struct import Struct
            word = Struct(">H")
            return b''.join((word.pack(m.CSM_MSG_ID) for m in messages))

        while True:
            incoming_message = await read_csm(stream)
            print("incoming", incoming_message)
            if isinstance(incoming_message, StartIdentification):
                identification = IdentificationInformation(
                    name="raspberrypi",
                    model_identifier="pi",
                    manufacturer="wiomoc",
                    serial_number="0122349",
                    fireware_version="1.0.1",
                    hardware_version="2.0",
                    messages_sent_by_accessory=messages_ids(VehicleStatusUpdate),
                    messages_received_from_accessory=messages_ids(StartExternalAccessoryProtocolSession,
                                                                  StopExternalAccessoryProtocolSession,
                                                                  StartVehicleStatusUpdates,
                                                                  StopVehicleStatusUpdates),
                    power_providing_capability=PowerProvidingCapability.NONE,
                    maximum_current_drawn_from_device=Uint16(20),
                    supported_external_accessory_protocol=[ExternalAccessoryProtocol(
                        id=Uint8(1),
                        name="de.wiomoc.test",
                        match_action=MatchAction.NONE,
                    )],
                    current_language="de",
                    supported_language=["de\0en"],
                    bluetooth_transport_component=[BluetoothTransportComponent(
                        id=Uint16(0),
                        name="blue",
                        supports_iap2_connection=True,
                        bluetooth_transport_mac=b'\xB8\x27\xEB\x23\x6A\xF4'
                    )],
                    vehicle_information_component=VehicleInformationComponent(
                        id=Uint16(0),
                        name="Tesla Model X",
                        engine_type=EngineType.ELECTRIC
                    ),
                    vehicle_status_component=VehicleStatusComponent(
                        id=Uint16(0),
                        name="Tesla Model X",
                        range_warning=True
                    ),
                    wireless_car_play_transport_component = WirelessCarPlayTransportComponent(
                        id=Uint16(2),
                        name="carp",
                        supports_iap2_connection=True,
                        supports_car_play = True
                    )
                )
                print(identification.csm_serialize())
                await write_csm(stream, identification)
            elif isinstance(incoming_message, IdentificationAccepted):
                return
            else:
                raise Exception("identification failed")

    async def main():
        def on_connection(reader, writer):
            print(reader, writer)

            async def iap_handler():
                conn = IAP2Connection(writer, reader, loop, max_outgoing=4)
                conn.start()
                stream = conn.control_session
                await handle_auth(stream)
                await handle_identification(stream)

            loop.create_task(iap_handler())

        BluetoothTransport(on_connection, loop)

    loop.create_task(main())
    loop.run_forever()
