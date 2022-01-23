#!/usr/bin/env python -u
# This file is part of python-functionfs
# Copyright (C) 2016-2021  Vincent Pelletier <plr.vincent@gmail.com>
#
# python-functionfs is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# python-functionfs is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with python-functionfs.  If not, see <http://www.gnu.org/licenses/>.

from collections import deque
import errno
import fcntl
import functools
import os
import select
import sys
import functionfs
from functionfs.gadget import (
    GadgetSubprocessManager,
    ConfigFunctionFFS,
)
import functionfs.ch9
import asyncio

# Large-ish buffer, to tolerate bursts without becoming a context switch storm.
BUF_SIZE = 1024 * 1024

trace = functools.partial(print, file=sys.stderr)

class EndpointOUTFile(functionfs.EndpointOUTFile, asyncio.StreamReader):
    def __init__(self, *args, **kw):
        functionfs.EndpointOUTFile.__init__(self, *args, **kw)
        asyncio.StreamReader.__init__(self)

    def onComplete(self, data, status):
        if data is None:
            trace('aio read completion error:', -status)
        else:
            trace('aio read completion received', len(data), 'bytes')
            self.feed_data(data)

class EndpointINFile(functionfs.EndpointINFile):
    def __init__(self, *args, **kw):
        self.__stranded_buffer_list_queue = deque()
        self._full = False
        super().__init__(*args, **kw)
        
    def write(self, data):
        if self._full:
            return
        if type(data) == bytes:
            data = bytearray(data)
        self.submit([bytearray(data)])

    def onComplete(self, buffer_list, user_data, status):
        if status < 0:
            trace('aio write completion error:', -status)
        else:
            trace('aio write completion sent', status, 'bytes')
        if status != -errno.ESHUTDOWN and self.__stranded_buffer_list_queue:
            buffer_list = self.__stranded_buffer_list_queue.popleft()
            self._full = not self.__stranded_buffer_list_queue
            return buffer_list
        return None

    def onSubmitEAGAIN(self, buffer_list, user_data):
        self.__stranded_buffer_list_queue.append(buffer_list)
        trace('send queue full, pause sending')
        self._full = True

    def forgetStranded(self):
        self.__stranded_buffer_list_queue.clear()

class USBCat(functionfs.Function):

    def __init__(self, path):
        fs_list, hs_list, ss_list = functionfs.getInterfaceInAllSpeeds(
            interface={
                'bInterfaceClass': functionfs.ch9.USB_CLASS_VENDOR_SPEC,
                'bInterfaceSubClass': 0xF0,
                'iInterface': 1,
            },
            endpoint_list=[
                {
                    'endpoint': {
                        'bEndpointAddress': functionfs.ch9.USB_DIR_IN,
                        'bmAttributes': functionfs.ch9.USB_ENDPOINT_XFER_BULK,
                    },
                }, {
                    'endpoint': {
                        'bEndpointAddress': functionfs.ch9.USB_DIR_OUT,
                        'bmAttributes': functionfs.ch9.USB_ENDPOINT_XFER_BULK,
                    },
                },
            ],
        )
        super().__init__(
            path,
            fs_list=fs_list,
            hs_list=hs_list,
            ss_list=ss_list,
            lang_dict={
                0x0409: [
                    "iAP Interface",
                ],
            },
        )

    def getEndpointClass(self, is_in, descriptor):
        return (EndpointINFile if is_in else EndpointOUTFile)

    def __enter__(self):
            result = super().__enter__()
            self.in_ep = self.getEndpoint(1)
            self.out_ep = self.getEndpoint(2)
            return result
        

    def onBind(self):
        trace('onBind')
        super().onBind()

    def onUnbind(self):
        trace('onUnbind')
        super().onUnbind()

    def onEnable(self):
        trace('onEnable')
        super().onEnable()

    def onDisable(self):
        trace('onDisable')
        self.in_ep.forgetStranded()
        super().onDisable()

    def onSuspend(self):
        trace('onSuspend')
        super().onSuspend()

    def onResume(self):
        trace('onResume')
        super().onResume()

class SubprocessCat(ConfigFunctionFFS):
    def getFunction(self):
        return USBCat(path=self._mountpoint)




loop = asyncio.get_event_loop()


def main():
    s = SubprocessCat()
    s.start(path="/sys/kernel/config/usb_gadget/isticktoit/ffs.sda")
    s.function = function = s.getFunction()
    loop.add_reader(function.eventfd.fileno(), function.processEvents)
    try:
       with function as f:
          async def g():
              input = f.getEndpoint(2)
              print(await input.readexactly(4))
              
          loop.create_task(g())
          out = f.getEndpoint(1)
          def w():
              out.write(b'\xFF\x55\x02\x00\xEE\x10')
              print("w")
              loop.call_later(1, w)
          w()
          loop.run_forever()
    except BaseException as e:
        s.join()
        raise e
       

if __name__ == '__main__':
    main()