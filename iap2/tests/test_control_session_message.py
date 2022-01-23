import unittest
from dataclasses import dataclass
from typing import Annotated, List

from iap2.control_session_message.identification import MatchAction, ExternalAccessoryProtocol, PowerProvidingCapability, IdentificationInformation, \
    BluetoothTransportComponent
from iap2.control_session_message import  Uint16, register_csm, Uint8, csm,  read_csm
from iap2.tests.utils import gen_pipe


class TestControlSessionMessage(unittest.TestCase):
    @dataclass
    @csm(0xAA01)
    class Test:
        @dataclass
        class TestGroup:
            num: Uint8 = None

        first: str = None
        second: Annotated[str, 100] = None
        group: Annotated[List[TestGroup], 101] = None

    def test_roundtrip(self):
        import asyncio
        loop = asyncio.get_event_loop()
        register_csm(IdentificationInformation)

        async def test():
            reader, writer = await gen_pipe(loop)
            expected_csm = IdentificationInformation(
                name="raspberrypi",
                model_identifier="pi",
                manufacturer="wiomoc",
                serial_number="0122349",
                fireware_version="1.0.1",
                hardware_version="2.0",
                messages_sent_by_accessory=b'',
                messages_received_from_accessory=b'123123',
                power_providing_capability=PowerProvidingCapability.NONE,
                maximum_current_drawn_from_device=Uint16(20),
                supported_external_accessory_protocol=[ExternalAccessoryProtocol(
                    id=Uint8(1),
                    name="de.wiomoc.test",
                    match_action=MatchAction.NONE,
                )],
                current_language="de",
                supported_language=["de", "en"],
                app_match_team_id="",
                bluetooth_transport_component=[BluetoothTransportComponent(
                    id=Uint16(0),
                    name="blue",
                    supports_iap2_connection=None,
                    bluetooth_transport_mac=b'\xB8\x27\xEB\x23\x6A\xF4'
                )]
            )

            async def write():
                writer.write(expected_csm.csm_serialize())
                await writer.drain()

            loop.create_task(write())
            actual_csm = await read_csm(reader)
            print(actual_csm)
            self.assertEqual(expected_csm, actual_csm)

        loop.run_until_complete(test())
