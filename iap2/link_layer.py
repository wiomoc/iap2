from dataclasses import dataclass
from typing import ClassVar
from struct import Struct
from functools import reduce
from collections import namedtuple
import asyncio

CONTROL_SYN = 0x80
CONTROL_ACK = 0x40
CONTROL_EAK = 0x20
CONTROL_RST = 0x10

loop = asyncio.get_event_loop()


@dataclass
class LinkPacketHeader:
    struct: ClassVar = Struct(">HHBBBB")
    start: ClassVar = 0xFF5A
    length: int
    control: int
    seq: int
    ack: int
    session_id: int

    @staticmethod
    def from_bytes(header_bytes):
        if not check_checksum(header_bytes):
            return None
        (start, length, control, seq, ack,
         session_id) = LinkPacketHeader.struct.unpack(header_bytes[:-1])
        if start != LinkPacketHeader.start:
            return None
        return LinkPacketHeader(length, control, seq, ack, session_id)

    def pack(self):
        header_bytes = LinkPacketHeader.struct.pack(LinkPacketHeader.start,
                                                    self.length, self.control,
                                                    self.seq, self.ack,
                                                    self.session_id)
        return header_bytes + bytes([gen_checksum(header_bytes)])


def signed_add(a, b):
    return (a + b) & 0xff


def gen_checksum(packet):
    return -reduce(signed_add, packet) & 0xff


def check_checksum(packet):
    return reduce(signed_add, packet) == 0


LSPSession = namedtuple('LSPSession', 'id type version')


@dataclass
class LinkSynchronizationPayload:
    struct: ClassVar = Struct(">BBHHHBB")
    version: ClassVar = 0x01
    max_outgoing: int
    max_len: int
    retransmission_timeout: int
    ack_timeout: int
    max_retransmissions: int
    max_ack: int
    sessions: list

    @staticmethod
    def from_bytes(payload):
        (version, max_outgoing, max_len, retransmission_timeout, ack_timeout,
         max_retransmissions,
         max_ack) = LinkSynchronizationPayload.struct.unpack(payload[:10])
        if version != LinkSynchronizationPayload.version:
            return None

        sessions_bytes = payload[10:]
        sessions = []
        for i in range(0, len(sessions_bytes), 3):
            sessions.append(LSPSession._make(sessions_bytes[i:i + 3]))
        return LinkSynchronizationPayload(max_outgoing, max_len,
                                          retransmission_timeout, ack_timeout,
                                          max_retransmissions, max_ack,
                                          sessions)

    def pack(self):
        payload = LinkSynchronizationPayload.struct.pack(
            LinkSynchronizationPayload.version, self.max_outgoing,
            self.max_len, self.retransmission_timeout, self.ack_timeout,
            self.max_retransmissions, self.max_ack)
        return payload + b''.join([bytes([*s]) for s in self.sessions])


STATE_DETECT_IAP2_SUPPORT = 0
STATE_NEGOTIATE = 1
STATE_NORMAL = 2
STATE_DEAD = 3

IAP2_MARKER = b'\xFF\x55\x02\x00\xEE\x10'
EA_SESSION_ID_STRUCT = Struct(">H")


class IAPPacket:
    def __init__(self, data, psn=None, session_id=0):
        self.psn = psn
        self.data = data
        self.session_id = session_id


class IAP2Stream:
    def __init__(self, conn, session_id, stream_id=None):
        self.conn = conn
        self.session_id = session_id
        self.stream_id = stream_id
        self.out_buffer = bytearray()
        self.in_buffer = bytearray()
        self.in_waiter_fut = None
        self.in_waiter_count = None
        if self.stream_id != None:
            self.out_buffer += EA_SESSION_ID_STRUCT.pack(self.stream_id)
        self.closed = False

    def write(self, data):
        self.out_buffer += data
        # while len(self.out_buffer) >= self.conn.lsp.max_len:
        #    await self.conn.write_allowed_event.wait()
        #    self.conn.send_packet(
        #        IAPPacket(self.out_buffer[:self.conn.lsp.max_len],
        #                  session_id=self.id))
        #    del self.out_buffer[:self.conn.lsp.max_len]

    async def drain(self):
        if len(self.out_buffer) == 0:
            return
        await self.conn.write_allowed_event.wait()
        self.conn.send_packet(
            IAPPacket(self.out_buffer, session_id=self.session_id))
        self.out_buffer = bytearray()
        if self.stream_id != None:
            self.out_buffer += EA_SESSION_ID_STRUCT.pack(self.stream_id)

    def received_data(self, data):
        self.in_buffer += data
        if self.in_waiter_fut and self.in_waiter_count <= len(self.in_buffer):
            self.in_waiter_fut.set_result(True)
            self.in_waiter_fut = None

    async def readexactly(self, nbytes):
        if self.in_waiter_fut:
            return

        if len(self.in_buffer) < nbytes:
            if self.closed:
                raise asyncio.exceptions.IncompleteReadError(partial=self.in_buffer, expected=nbytes)
            self.in_waiter_count = nbytes
            fut = self.conn.loop.create_future()
            self.in_waiter_fut = fut
            await fut
            if self.closed:
                raise asyncio.exceptions.IncompleteReadError(partial=self.in_buffer, expected=nbytes)

        d = self.in_buffer[:nbytes]
        del self.in_buffer[:nbytes]
        return d

    def feed_eof(self):
        self.closed = True
        if self.in_waiter_fut:
            self.in_waiter_fut.set_result(True)
            self.in_waiter_fut = None


class IAP2Connection:
    CONTROL_SESSION_ID = 10
    EA_SESSION_ID = 11

    def __init__(self,
                 output=None,
                 input=None,
                 loop=asyncio.get_event_loop(),
                 max_outgoing=4,
                 max_outgoing_delta=0,
                 on_error=None):
        self.on_error = on_error
        self.state = None
        self.lsp = LinkSynchronizationPayload(
            max_outgoing=max_outgoing,
            max_len=4096,
            retransmission_timeout=1035,
            ack_timeout=23,
            max_retransmissions=3,
            max_ack=3,
            sessions=[
                LSPSession(id=IAP2Connection.CONTROL_SESSION_ID,
                           type=0,
                           version=1),
                LSPSession(id=IAP2Connection.EA_SESSION_ID, type=2, version=1)
            ])
        self.max_outgoing_delta = max_outgoing_delta
        self.sent_psn = 50
        self.last_sent_acknowledged_psn = None
        self.unack_packets = []
        self.queued_packets = []

        self.last_received_in_sequence_psn = 0
        self.last_acked_psn = None
        self.initial_received_psn = None
        self.received_out_of_sequence = []
        self.cumulative_received = 0
        self.loop = loop
        self.output = output
        self.input = input
        self.send_ack_timer = None
        self.recv_ack_timer = None
        self.write_allowed_event = asyncio.Event()
        self.control_session = IAP2Stream(self,
                                          IAP2Connection.CONTROL_SESSION_ID)
        self.ea_streams = dict()
        self._receive_loop_task = None

    def create_ea_stream(self, stream_id):
        stream = IAP2Stream(self, IAP2Connection.EA_SESSION_ID, stream_id)
        self.ea_streams[stream_id] = stream
        return stream

    def write_packet(self, payload=None, seq=0, control=0, session_id=0):
        self.cumulative_received = 0
        if payload:
            length = len(payload) + 10
        else:
            length = 9
        header = LinkPacketHeader(control=control,
                                  length=length,
                                  seq=seq,
                                  ack=self.last_received_in_sequence_psn,
                                  session_id=session_id)
        print(">", header)
        header_bytes = header.pack()
        if payload:
            self.output.write(header_bytes + payload +
                              bytes([gen_checksum(payload)]))
        else:
            self.output.write(header_bytes)

    def send_ack(self):
        self.write_packet(seq=self.sent_psn, control=CONTROL_ACK)

    def send_eak(self, num):
        self.write_packet(bytes(num), seq=self.sent_psn, control=CONTROL_EAK)

    def send_data(self, p):
        self.write_packet(p.data,
                          seq=p.psn,
                          control=CONTROL_ACK,
                          session_id=p.session_id)

    def start(self):
        if self.state:
            return
        self._receive_loop_task = self.loop.create_task(self.receive_loop())
        self.state = STATE_DETECT_IAP2_SUPPORT
        self.send_detect_iap2_support()

    def send_detect_iap2_support(self):
        if self.state != STATE_DETECT_IAP2_SUPPORT:
            return
        self.output.write(IAP2_MARKER)
        self.loop.call_later(1, self.send_detect_iap2_support)

    def send_negotiate(self):
        if self.state != STATE_NEGOTIATE:
            return
        lsp_bytes = self.lsp.pack()
        self.write_packet(lsp_bytes, self.sent_psn, CONTROL_SYN)
        self.loop.call_later(0.5, self.send_negotiate)

    async def receive_loop(self):
        try:
            recv_marker = await self.input.readexactly(len(IAP2_MARKER))
            if recv_marker != IAP2_MARKER:
                self.bailout("IAP2 not supported")
                return
            if hasattr(self.input, "reset"):
                self.input.reset()
            self.state = STATE_NEGOTIATE
            self.send_negotiate()
            while True:
                header_bytes = await self.input.readexactly(9)
                while True:
                    if int(header_bytes[0]) << 8 | int(
                            header_bytes[1]) == LinkPacketHeader.start:
                        break
                    header_bytes = header_bytes[1:] + await self.input.readexactly(
                        1)
                header = LinkPacketHeader.from_bytes(header_bytes)
                print("<", header)
                if not header:
                    continue
                payload = None
                if header.length > 9:
                    payload_with_checksum = await self.input.readexactly(
                        header.length - 9)
                    if not check_checksum(payload_with_checksum):
                        continue
                    payload = payload_with_checksum[:-1]
                if hasattr(self.input, "reset"):
                    self.input.reset()
                if (header.control & CONTROL_SYN) != 0:
                    lsp = LinkSynchronizationPayload.from_bytes(payload)
                    if not lsp:
                        continue
                    self.handle_syn(lsp, header.seq)
                if (header.control & CONTROL_ACK) != 0:
                    self.cumulative_received += 1
                    self.handle_ack(header.ack)
                if (header.control & CONTROL_EAK) != 0 and payload:
                    self.handle_eak([int(x) for x in payload])
                if (header.control & ~CONTROL_ACK) == 0 and payload != None:
                    self.handle_data(
                        IAPPacket(payload, header.seq, header.session_id))
                if self.cumulative_received >= self.lsp.max_ack:
                    self.cumulative_received = 0
                    self.last_acked_psn = self.last_received_in_sequence_psn
                    self.send_ack()
        except asyncio.exceptions.IncompleteReadError:
            try:
                self.state = STATE_DEAD
                self.output.close()
                self.control_session.feed_eof()
                for stream in self.ea_streams.values():
                    stream.feed_eof()
            except:
                pass
        except Exception as e:
            self.bailout(e)

    def bailout(self, error):
        if self.state == STATE_DEAD:
            return
        self.state = STATE_DEAD
        try:
            self.output.close()
        except:
            pass
        try:
            self.control_session.feed_eof()
            for stream in self.ea_streams.values():
                stream.feed_eof()
        except:
            pass
        if self._receive_loop_task:
            try:
                self._receive_loop_task.cancel()
            except:
                pass
        if self.on_error:
            self.on_error(error)

    def send_packet(self, p):
        if distance(self.sent_psn, self.last_sent_acknowledged_psn
                    ) > self.lsp.max_outgoing or self.state != STATE_NORMAL:
            self.queued_packets.append(p)
            self.write_allowed_event.clear()
            return

        self.sent_psn = signed_add(self.sent_psn, 1)
        p.counter = 0
        p.psn = self.sent_psn
        p.timeout = self.loop.time() + self.lsp.retransmission_timeout / 1000
        self.disarm_send_ack_timer()
        self.send_data(p)
        self.last_acked_psn = self.last_received_in_sequence_psn
        self.rearm_recv_ack_timer(p.timeout)
        self.unack_packets.append(p)

    def handle_syn(self, lsp, psn):
        if self.state != STATE_NEGOTIATE:
            return
        print("Device:", lsp)
        print("Accessory:", self.lsp)
        self.lsp = lsp
        self.last_received_in_sequence_psn = psn
        self.last_acked_psn = psn
        self.send_ack()

    def handle_ack(self, num):
        if self.state == STATE_NEGOTIATE:
            self.state = STATE_NORMAL
            self.write_allowed_event.set()
        self.last_sent_acknowledged_psn = num
        while len(self.unack_packets) != 0:
            if distance(
                    self.unack_packets.pop(0).psn,
                    self.last_sent_acknowledged_psn) == 0:
                if len(self.unack_packets) != 0:
                    self.rearm_recv_ack_timer(self.unack_packets[0].timeout)
                    break
        else:
            self.disarm_recv_ack_timer()

        while distance(self.sent_psn, self.last_sent_acknowledged_psn
                       ) < self.lsp.max_outgoing and len(
            self.queued_packets) > 0:
            self.send_packet(self.queued_packets.pop(0))
            self.write_allowed_event.set()

    def on_expect_ack_timer(self):
        unack_packets = sorted(self.unack_packets, key=lambda x: x.timeout)
        p = unack_packets[0]
        self.send_data(p)
        self.disarm_send_ack_timer()
        p.timeout = self.loop.time() + self.lsp.retransmission_timeout / 1000
        p.counter += 1
        if p.counter == self.lsp.max_retransmissions:
            self.bailout(p)
        if len(unack_packets) > 1:
            self.rearm_recv_ack_timer(unack_packets[1].timeout)

    def handle_eak(self, nums):
        if self.state != STATE_NORMAL:
            return
        for p in self.unack_packets:
            if p.psn in nums:
                p.counter += 1
                if p.counter == self.lsp.max_retransmissions:
                    self.bailout(p)
                    continue
                self.send_data(p)
                self.disarm_send_ack_timer()
                self.rearm_recv_ack_timer(p.timeout)

    def on_send_ack_timer(self):
        self.last_acked_psn = self.last_received_in_sequence_psn
        self.send_ack()

    def handle_data(self, p):
        d = distance(p.psn, self.last_received_in_sequence_psn)
        if d > self.lsp.max_outgoing + 10 or d == 0:
            self.send_ack()
            return

        if d > 1:
            self.received_out_of_sequence.append(p)
            if d >= self.lsp.max_outgoing:
                eak = []
                x = self.last_received_in_sequence_psn
                while distance(p.psn, x) > 1:
                    x = signed_add(x, 1)
                    eak.append(x)
                self.disarm_send_ack_timer()
                self.send_eak(eak)
            return

        self.received_out_of_sequence.append(p)
        for pp in sorted(self.received_out_of_sequence,
                         key=lambda x: distance(
                             x.psn, self.last_received_in_sequence_psn)):
            if distance(pp.psn, self.last_received_in_sequence_psn) > 1:
                break
            self.received_data(pp)
            self.last_received_in_sequence_psn = pp.psn
            self.received_out_of_sequence.remove(pp)

        if distance(self.last_received_in_sequence_psn, self.last_acked_psn
                    ) >= self.lsp.max_outgoing - self.max_outgoing_delta:
            self.disarm_send_ack_timer()
            self.last_acked_psn = self.last_received_in_sequence_psn
            self.send_ack()
        else:
            self.rearm_send_ack_timer()

    def received_data(self, p):
        if p.session_id == IAP2Connection.CONTROL_SESSION_ID:
            self.control_session.received_data(p.data)
        elif p.session_id == IAP2Connection.EA_SESSION_ID and len(p.data) >= 2:
            stream_id = EA_SESSION_ID_STRUCT.unpack(p.data[:2])[0]
            stream = self.ea_streams.get(stream_id)
            if stream:
                stream.received_data(p.data[2:])

    def disarm_send_ack_timer(self):
        if self.send_ack_timer:
            self.send_ack_timer.cancel()
            self.send_ack_timer = None

    def rearm_send_ack_timer(self):
        if self.send_ack_timer:
            self.send_ack_timer.cancel()
        self.send_ack_timer = self.loop.call_later(self.lsp.ack_timeout / 1000,
                                                   self.on_send_ack_timer)

    def disarm_recv_ack_timer(self):
        if self.recv_ack_timer:
            self.recv_ack_timer.cancel()
            self.recv_ack_timer = None

    def rearm_recv_ack_timer(self, time):
        if self.recv_ack_timer:
            self.recv_ack_timer.cancel()
        self.recv_ack_timer = self.loop.call_at(time, self.on_expect_ack_timer)

    def close(self):
        self.input.feed_eof()


def distance(a, b):
    if b is None:
        return 0
    elif a >= b:
        return a - b
    else:
        return a + 256 - b
