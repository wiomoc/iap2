import asyncio
import unittest
from unittest.mock import Mock, call
import random

from iap2.link_layer import CONTROL_SYN, CONTROL_ACK, LinkSynchronizationPayload, LinkPacketHeader, IAP2_MARKER, \
    STATE_NORMAL, gen_checksum, IAP2Connection, LSPSession
from utils import gen_pipe


class TestLinkPacketHeader(unittest.TestCase):
    def test_round_trip(self):
        header_bytes = b'\xffZ\x00\x1a\x80+\x00\x00\xe2'
        header = LinkPacketHeader.from_bytes(header_bytes)
        self.assertEqual(
            header,
            LinkPacketHeader(length=26,
                             control=128,
                             seq=43,
                             ack=0,
                             session_id=0))
        repacked_header_bytes = header.pack()
        self.assertEqual(repacked_header_bytes, header_bytes)

    def test_invalid_check(self):
        header_bytes = b'\xffZ\x00\x1a\x80+\x00\x00\xe1'
        header = LinkPacketHeader.from_bytes(header_bytes)
        self.assertIsNone(header)

    def test_invalid_start(self):
        header_bytes = b'\xfeZ\x00\x1a\x80+\x00\x00\xe2'
        header = LinkPacketHeader.from_bytes(header_bytes)
        self.assertIsNone(header)


class TestLinkSynchronizationPayload(unittest.TestCase):
    def test_round_trip(self):
        payload = b'\x01\x05\x10\x00\x04\x0B\x00\x17\x03\x03\x0A\x00\x01\x0B\x02\x01'
        lsp = LinkSynchronizationPayload.from_bytes(payload)
        self.assertEqual(
            lsp,
            LinkSynchronizationPayload(max_outgoing=5,
                                       max_len=4096,
                                       retransmission_timeout=1035,
                                       ack_timeout=23,
                                       max_retransmissions=3,
                                       max_ack=3,
                                       sessions=[
                                           LSPSession(id=10, type=0,
                                                      version=1),
                                           LSPSession(id=11, type=2, version=1)
                                       ]))
        repacked_payload = lsp.pack()
        self.assertEqual(repacked_payload, payload)


class TestIAP2Connection(unittest.TestCase):
    class TestPacket:
        def __init__(self):
            self.id = random.random()

    def test_normal(self):
        conn = IAP2Connection(max_outgoing=3)
        conn.state = STATE_NORMAL
        conn.sent_psn = 199
        conn.rearm_send_ack_timer = Mock()
        conn.received_data = Mock()
        conn.send_data = Mock()
        conn.disarm_send_ack_timer = Mock()
        conn.rearm_recv_ack_timer = Mock()
        conn.last_acked_psn = 99
        conn.last_received_in_sequence_psn = 99

        p1 = TestIAP2Connection.TestPacket()
        p1.psn = 100

        conn.handle_data(p1)

        conn.received_data.assert_called_with(p1)
        conn.rearm_send_ack_timer.assert_called()

        p2 = TestIAP2Connection.TestPacket()

        conn.send_packet(p2)

        conn.send_data.assert_called_with(p2)
        self.assertEqual(conn.last_received_in_sequence_psn, p1.psn)
        conn.disarm_send_ack_timer.assert_called()
        conn.rearm_recv_ack_timer.assert_called()
        self.assertEqual(p2.psn, 200)
        self.assertEqual(conn.unack_packets, [p2])

        p3 = TestIAP2Connection.TestPacket()
        p3.psn = 101

        conn.handle_data(p3)

        conn.received_data.assert_called_with(p3)
        conn.rearm_send_ack_timer.assert_called()

        conn.disarm_recv_ack_timer = Mock()

        conn.handle_ack(200)

        conn.disarm_recv_ack_timer.assert_called()
        self.assertEqual(conn.unack_packets, [])

        p4 = TestIAP2Connection.TestPacket()
        p4.psn = 102

        conn.handle_data(p4)

        conn.handle_ack(200)
        conn.disarm_recv_ack_timer.assert_called()

        p5 = TestIAP2Connection.TestPacket()

        conn.send_packet(p5)

        conn.send_data.assert_called_with(p5)
        self.assertEqual(conn.last_received_in_sequence_psn, p4.psn)
        conn.disarm_send_ack_timer.assert_called()
        conn.rearm_recv_ack_timer.assert_called()
        self.assertEqual(p5.psn, 201)

    def test_ack_timeout(self):
        conn = IAP2Connection(max_outgoing=3)
        conn.state = STATE_NORMAL
        conn.sent_psn = 199
        conn.rearm_recv_ack_timer = Mock()
        conn.send_data = Mock()
        conn.disarm_send_ack_timer = Mock()
        conn.last_received_in_sequence_psn = 99
        conn.disarm_recv_ack_timer = Mock()

        p1 = TestIAP2Connection.TestPacket()

        conn.send_packet(p1)

        conn.send_data.assert_called_with(p1)
        conn.rearm_recv_ack_timer.assert_called()

        p2 = TestIAP2Connection.TestPacket()

        conn.send_packet(p2)

        conn.send_data.assert_called_with(p2)
        conn.rearm_recv_ack_timer.assert_called()

        conn.on_expect_ack_timer()
        conn.send_data.assert_called_with(p1)

        conn.rearm_recv_ack_timer.assert_called()
        conn.on_expect_ack_timer()
        conn.send_data.assert_called_with(p2)

        conn.handle_ack(p1.psn)
        self.assertEqual(conn.unack_packets, [p2])

        conn.on_expect_ack_timer()
        conn.send_data.assert_called_with(p2)

        conn.handle_ack(p2.psn)

        conn.disarm_recv_ack_timer.asser_called()

    def test_buffer(self):
        conn = IAP2Connection(max_outgoing=2)
        conn.state = STATE_NORMAL
        conn.sent_psn = 199
        conn.last_sent_acknowledged_psn = 198
        conn.rearm_recv_ack_timer = Mock()
        conn.disarm_send_ack_timer = Mock()
        conn.disarm_recv_ack_timer = Mock()
        conn.send_data = Mock()

        p1 = TestIAP2Connection.TestPacket()
        conn.send_packet(p1)
        conn.send_data.reset_mock()
        conn.rearm_recv_ack_timer.assert_called()

        p2 = TestIAP2Connection.TestPacket()
        conn.send_packet(p2)
        conn.send_data.assert_called_with(p2)
        conn.send_data.reset_mock()
        conn.rearm_recv_ack_timer.assert_called()

        p3 = TestIAP2Connection.TestPacket()
        conn.send_packet(p3)
        conn.send_data.assert_not_called()

        conn.handle_ack(p2.psn)
        conn.send_data.assert_called_with(p3)

    def test_cumulative(self):
        conn = IAP2Connection(max_outgoing=2)
        conn.state = STATE_NORMAL
        conn.last_acked_psn = 99
        conn.last_received_in_sequence_psn = 99
        conn.rearm_send_ack_timer = Mock()
        conn.received_data = Mock()

        p1 = TestIAP2Connection.TestPacket()
        p1.psn = 100

        conn.handle_data(p1)

        conn.received_data.assert_called_with(p1)
        conn.rearm_send_ack_timer.assert_called()

        p2 = TestIAP2Connection.TestPacket()
        p2.psn = 101
        conn.disarm_send_ack_timer = Mock()
        conn.send_ack = Mock()

        conn.handle_data(p2)

        conn.received_data.assert_called_with(p2)
        conn.send_ack.assert_called()
        self.assertEqual(conn.last_received_in_sequence_psn, p2.psn)
        conn.disarm_send_ack_timer.assert_called()

    def test_out_of_order(self):
        conn = IAP2Connection(max_outgoing=10)
        conn.state = STATE_NORMAL
        conn.last_acked_psn = 102
        conn.last_received_in_sequence_psn = 102
        conn.rearm_send_ack_timer = Mock()
        conn.received_data = Mock()

        p1 = TestIAP2Connection.TestPacket()
        p1.psn = 103

        conn.handle_data(p1)

        conn.received_data.assert_called_with(p1)
        conn.rearm_send_ack_timer.assert_called()

        p2 = TestIAP2Connection.TestPacket()
        p2.psn = 107

        conn.handle_data(p2)

        p3 = TestIAP2Connection.TestPacket()
        p3.psn = 105

        conn.handle_data(p3)

        p4 = TestIAP2Connection.TestPacket()
        p4.psn = 104
        conn.disarm_send_ack_timer = Mock()
        conn.send_ack = Mock()

        conn.handle_data(p4)

        conn.received_data.assert_has_calls([call(p4), call(p3)])
        self.assertEqual(conn.last_received_in_sequence_psn, p3.psn)
        conn.rearm_send_ack_timer.assert_called()

    def test_out_of_order_overflow(self):
        conn = IAP2Connection(max_outgoing=3)
        conn.state = STATE_NORMAL
        conn.last_acked_psn = 253
        conn.last_received_in_sequence_psn = 253
        conn.rearm_send_ack_timer = Mock()
        conn.received_data = Mock()

        p1 = TestIAP2Connection.TestPacket()
        p1.psn = 254

        conn.handle_data(p1)

        conn.received_data.assert_called_with(p1)
        conn.rearm_send_ack_timer.assert_called()

        p2 = TestIAP2Connection.TestPacket()
        p2.psn = 0

        conn.handle_data(p2)

        p3 = TestIAP2Connection.TestPacket()
        p3.psn = 255
        conn.disarm_send_ack_timer = Mock()
        conn.send_ack = Mock()

        conn.handle_data(p3)

        conn.received_data.assert_has_calls([call(p3), call(p2)])
        conn.send_ack.assert_called()
        self.assertEqual(conn.last_received_in_sequence_psn, p2.psn)
        conn.disarm_send_ack_timer.assert_called()

    def test_eak(self):
        conn = IAP2Connection(max_outgoing=2)
        conn.state = STATE_NORMAL
        conn.last_received_in_sequence_psn = 102
        conn.last_acked_psn = 102
        conn.rearm_send_ack_timer = Mock()
        conn.received_data = Mock()

        p1 = TestIAP2Connection.TestPacket()
        p1.psn = 103

        conn.handle_data(p1)

        conn.received_data.assert_called_with(p1)
        conn.rearm_send_ack_timer.assert_called()

        p2 = TestIAP2Connection.TestPacket()
        p2.psn = 105
        conn.disarm_send_ack_timer = Mock()
        conn.send_ack = Mock()
        conn.send_eak = Mock()

        conn.handle_data(p2)

        conn.disarm_send_ack_timer.assert_called()
        conn.send_eak.assert_called_with([104])
        self.assertEqual(conn.last_received_in_sequence_psn, p1.psn)

    def test_eak_overflow(self):
        conn = IAP2Connection(max_outgoing=2)
        conn.state = STATE_NORMAL
        conn.last_received_in_sequence_psn = 254
        conn.last_acked_psn = 254
        conn.rearm_send_ack_timer = Mock()
        conn.received_data = Mock()

        p1 = TestIAP2Connection.TestPacket()
        p1.psn = 255

        conn.handle_data(p1)

        conn.received_data.assert_called_with(p1)
        conn.rearm_send_ack_timer.assert_called()

        p2 = TestIAP2Connection.TestPacket()
        p2.psn = 1
        conn.disarm_send_ack_timer = Mock()
        conn.send_ack = Mock()
        conn.send_eak = Mock()

        conn.handle_data(p2)

        conn.disarm_send_ack_timer.assert_called()
        conn.send_eak.assert_called_with([0])
        self.assertEqual(conn.last_received_in_sequence_psn, p1.psn)


def async_test(f):
    def wrapper(*args, **kwargs):
        coro = asyncio.coroutine(f)
        future = coro(*args, **kwargs)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(future)

    return wrapper


class SmokeTest(unittest.TestCase):
    @async_test
    async def test(self):
        loop = asyncio.get_event_loop()
        input_rx, input_tx = await gen_pipe(loop)
        output_rx, output_tx = await gen_pipe(loop)
        conn = IAP2Connection(
            output_tx,
            input_rx,
            loop,
            max_outgoing=8,
        )
        conn.start()

        init = await output_rx.readexactly(6)
        self.assertEqual(init, IAP2_MARKER)
        input_tx.write(IAP2_MARKER)
        await input_tx.drain()

        header_bytes = await output_rx.readexactly(9)
        header = LinkPacketHeader.from_bytes(header_bytes)
        lsp_bytes = (await output_rx.readexactly(header.length - 9))[:-1]
        lsp = LinkSynchronizationPayload.from_bytes(lsp_bytes)
        self.assertEqual(lsp, conn.lsp)

        header.control = CONTROL_SYN | CONTROL_ACK
        header.ack = header.seq
        header.seq = 200

        input_tx.write(b'\x30')  # Fault
        input_tx.write(header.pack())
        input_tx.write(lsp_bytes)
        input_tx.write(bytes([gen_checksum(lsp_bytes)]))
        await input_tx.drain()
        await asyncio.sleep(1)
        self.assertEqual(conn.state, STATE_NORMAL)
        header_bytes = await output_rx.readexactly(9)
        header = LinkPacketHeader.from_bytes(header_bytes)

        header.ack = 50
        header.seq = 201
        header.control = 0
        header.session_id = 10

        payload = b"hello world!"
        header.length = 10 + len(payload)
        input_tx.write(header.pack())
        input_tx.write(payload)
        input_tx.write(bytes([gen_checksum(payload)]))

        await asyncio.sleep(1)

        header_bytes = await output_rx.readexactly(9)
        header = LinkPacketHeader.from_bytes(header_bytes)

        stream = conn.create_ea_stream(0x42)
        stream.write(b'life')
        await stream.drain()

        header_bytes = await output_rx.readexactly(9)
        header = LinkPacketHeader.from_bytes(header_bytes)
        payload = (await output_rx.readexactly(header.length - 9))[:-1]
        self.assertEqual(payload, b'\x00\x42life')

        header.ack = 51
        header.seq = 202
        header.control = 0
        header.session_id = 11
        payload = b"\x00\x42abc"
        header.length = 10 + len(payload)
        input_tx.write(header.pack())
        input_tx.write(payload)
        input_tx.write(bytes([gen_checksum(payload)]))
        await input_tx.drain()
        self.assertEqual(await stream.readexactly(3), b'abc')

        control_session = conn.control_session
        control_session.write(b'pong')
        await control_session.drain()
        header_bytes = await output_rx.readexactly(9)
        header = LinkPacketHeader.from_bytes(header_bytes)
        payload = (await output_rx.readexactly(header.length - 9))[:-1]
        self.assertEqual(payload, b'pong')
        self.assertEqual(await control_session.readexactly(5), b'hello')
        loop.call_soon(lambda: input_rx.feed_eof())
        self.assertEqual(await control_session.readexactly(5), b' worl')

        with self.assertRaises(asyncio.exceptions.IncompleteReadError):
            await control_session.readexactly(5)

        with self.assertRaises(asyncio.exceptions.IncompleteReadError):
            await stream.readexactly(5)

    @async_test
    async def test_bailout(self):
        on_error = Mock()
        loop = asyncio.get_event_loop()
        input_rx, input_tx = await gen_pipe(loop)
        output_rx, output_tx = await gen_pipe(loop)
        conn = IAP2Connection(
            output_tx,
            input_rx,
            loop,
            max_outgoing=8,
            on_error=on_error
        )
        conn.start()

        init = await output_rx.readexactly(6)
        self.assertEqual(init, IAP2_MARKER)
        input_tx.write(IAP2_MARKER)
        await input_tx.drain()

        exception = Exception("42")
        input_rx.set_exception(exception)
        await asyncio.sleep(1)

        on_error.assert_called_with(exception)
