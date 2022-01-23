import usb1
import threading
import queue
import hid
import asyncio


class BaseUSBDeviceHandler:
    def __init__(self):
        context = usb1.USBContext()
        context.open()

        loop = asyncio.get_event_loop()

        def added_cb(fd, events):
            if events & 1:
                loop.add_reader(fd, context.handleEventsTimeout)
            if events & 4:
                loop.add_writer(fd, context.handleEventsTimeout)
            print("add", fd, events)

        def removed_cb(fd):
            print("rem", fd)
            loop.remove_reader(fd)
            loop.remove_writer(fd)

        for fd, events in context.getPollFDList():
            added_cb(fd, events)

        context._USBContext__has_pollfd_finalizer = True
        context.setPollFDNotifiers(added_cb=added_cb, removed_cb=removed_cb)
        context.setDebug(usb1.LOG_LEVEL_DEBUG)

        def hotplug_callback(context, device, event):
            print("event", repr(device), event)
            if event == usb1.HOTPLUG_EVENT_DEVICE_ARRIVED:
                loop.create_task(self._handle_new_device(device))

        context.hotplugRegisterCallback(callback=hotplug_callback, vendor_id=0x5ac)
        self._context = context

    def close(self):
        self._context.setPollFDNotifiers(None, None)
        self._context.close()


class USBRoleSwitchHandler(BaseUSBDeviceHandler):
    def __init__(self, after_role_switch, car_play=False):
        super().__init__()
        self._after_role_switch = after_role_switch
        self._car_play = car_play

    async def _handle_new_device(self, device):
        open_device = device.open()

        await _usb_control_transfer(
            open_device, usb1.RECIPIENT_DEVICE | usb1.LIBUSB_REQUEST_TYPE_VENDOR,
            0x51, 1 if self._car_play else 0, 0, 0)
        self._after_role_switch()


class USBDeviceTransport(BaseUSBDeviceHandler):
    def __init__(self, on_connection):
        super().__init__()
        self._on_connection = on_connection

    async def _handle_new_device(self, device):
        CONFIGURATION_VALUE = 2
        configs = [
            c for c in device.iterConfigurations()
            if c.getConfigurationValue() == CONFIGURATION_VALUE
        ]
        config = configs[0]

        interfaces = [
            s for i in config.iterInterfaces() for s in i.iterSettings()
            if s.getClassTuple() == (3, 0)
        ]
        interface_setting = interfaces[0]
        interface_num = interface_setting.getNumber()
        endpoints = list(interface_setting.iterEndpoints())
        endpoint = endpoints[0]
        print(interface_num)

        open_device = device.open()
        open_device.setConfiguration(CONFIGURATION_VALUE)

        report_descriptor = await _usb_control_transfer(
            open_device, usb1.ENDPOINT_IN | usb1.RECIPIENT_INTERFACE,
            usb1.REQUEST_GET_DESCRIPTOR, (usb1.DT_REPORT << 8), interface_num,
            2000)
        print(report_descriptor)
        output_report_ids = []
        input_report_ids = dict()
        report_id = None
        report_count = None
        for tag, item in get_descriptor_items(report_descriptor):
            if tag == 0x84:
                report_id = item[0]
            elif tag == 0x94:
                report_count = int(item[0]) if len(
                    item) == 1 else int(item[1]) << 8 | int(item[0])
            elif tag == 0x90:
                output_report_ids.append((report_id, report_count))
            elif tag == 0x80:
                input_report_ids[report_id] = report_count

        print(output_report_ids)
        print(input_report_ids)

        hid_device = hid.Device(vid=device.getVendorID(),
                                pid=device.getProductID(),
                                serial=device.getSerialNumber())
        w = HIDWriter(hid_device, output_report_ids)
        r = HIDReader(hid_device, input_report_ids)
        self._on_connection(w, r)


def _usb_control_transfer(device, request_type, request, value, index, length):
    transfer = device.getTransfer()
    future = asyncio.get_event_loop().create_future()

    def cb(transfer):
        status = transfer.getStatus()
        if status == usb1.LIBUSB_TRANSFER_COMPLETED:
            future.set_result(transfer.getBuffer()[:transfer.getActualLength()])
        else:
            future.set_exception(IOError(f"USB error {status}"))

    transfer.setControl(request_type, request, value, index, length, callback=cb)
    transfer.submit()
    return future


def get_descriptor_items(descriptor):
    i = 0
    while i < len(descriptor):
        tag = descriptor[i]
        if tag == 0xFE:
            size = descriptor[i + 1]
            tag = descriptor[i + 2]
            i += 3
            data = descriptor[i:i + size]
            i += size
        else:
            size = (1 << (tag & 3)) >> 1
            i += 1
            data = descriptor[i:i + size]
            tag &= 0xFC
            i += size
        yield (tag, data)


class HIDReader:
    def __init__(self, hid_device, input_report_ids):
        self._loop = asyncio.get_event_loop()
        self._hid_device = hid_device
        self._input_report_ids = input_report_ids
        self._read_buffer_semaphore = threading.Semaphore(value=3)
        self._read_buffer_queue = asyncio.Queue()
        self._max_len = max(input_report_ids.values())
        threading.Thread(target=self.read_loop).start()
        self._read_buffer = None

    async def readexactly(self, nbytes):
        if not self._read_buffer or len(self._read_buffer) == 0:
            self._read_buffer_semaphore.release()
            self._read_buffer = await self._read_buffer_queue.get()

        if len(self._read_buffer) >= nbytes:
            b = self._read_buffer[:nbytes]
            self._read_buffer = self._read_buffer[nbytes:]
            return b
        else:
            b = bytearray(self._read_buffer)
            while len(b) <= nbytes:
                self._read_buffer_semaphore.release()
                b.extend(await self._read_buffer_queue.get())
            self._read_buffer = b[nbytes:]
            return b[:nbytes]

    def reset(self):
        self.read_buffer = None

    def read_loop(self):
        buf = bytearray()
        while True:
            self._read_buffer_semaphore.acquire()
            while True:
                report = self._hid_device.read(self._max_len + 2)
                if len(report) <= 2:
                    continue
                lcb = report[1]
                if lcb & 1:
                    buf.clear()
                    buf.extend(report[2:])
                elif lcb & 2:
                    buf.extend(report[2:])
                else:
                    if len(buf) > 0:
                        buf.extend(report[2:])
                        packet = bytes(buf)
                        buf.clear()
                    else:
                        packet = report[2:]
                    self._loop.call_soon_threadsafe(
                        lambda: self._read_buffer_queue.put_nowait(packet))
                    break


class HIDWriter:
    def __init__(self, hid_device, output_report_ids):
        self._hid_device = hid_device
        self._output_report_ids = output_report_ids
        self._write_buffer_queue = queue.Queue()
        threading.Thread(target=self.write_loop).start()

    def write(self, bytes):
        self._write_buffer_queue.put_nowait(bytes)

    def write_loop(self):
        while True:
            first = True
            buf = self._write_buffer_queue.get()
            while len(buf) > 0:
                report_id = None
                report_count = None
                for id, count in self._output_report_ids:
                    count -= 1  # take lcb into account
                    report_id = id
                    report_count = count
                    if count > len(buf):
                        break
                lcb = 0
                if first:
                    first = False
                else:
                    lcb |= 1
                if report_count < len(buf):
                    lcb |= 2
                padding = b'\0' * max(report_count - len(buf), 0)
                self._hid_device.write(
                    bytes([report_id, lcb]) + buf[:report_count] + padding)
                buf = buf[report_count:]
