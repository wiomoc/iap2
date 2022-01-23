import asyncio
import os


async def gen_pipe(loop):
    read_fd, write_fd = os.pipe()
    reader = asyncio.StreamReader()
    read_protocol = asyncio.StreamReaderProtocol(reader)
    read_transport, _ = await loop.connect_read_pipe(lambda: read_protocol,
                                                     os.fdopen(read_fd))
    write_protocol = asyncio.StreamReaderProtocol(asyncio.StreamReader())
    write_transport, _ = await loop.connect_write_pipe(
        lambda: write_protocol, os.fdopen(write_fd, 'w'))
    writer = asyncio.StreamWriter(write_transport, write_protocol, None, loop)
    return reader, writer
