import time
import struct
import asyncio
import logging
import traceback
from utils import TimeoutHandler


class StableConnector:
    MAX_SIZE = 8 * 1024 * 1024

    def __init__(self):
        self._server_transport = None
        self._server_peername = None
        self._server_reader = None
        self._server_writer = None

    def close(self):
        if self._server_transport is not None:
            self._server_transport.close()

    async def _connector_ready(self):
        self._server_reader, self._server_writer = await asyncio.open_connection('127.0.0.1', 1521)
        self._server_transport = self._server_writer
        self._server_peername = self._server_transport.get_extra_info('peername')

    async def _server_polling(self):
        while True:
            try:
                recv_buffer = await self._server_reader.read(self.MAX_SIZE)
                # if server close connection, the `reader.at_eof()` returns True, we thing connection is closed
                if len(recv_buffer) == 0 and self._server_reader.at_eof():
                    raise ConnectionResetError
                if len(recv_buffer) != 0 and self._server_reader.at_eof():
                    raise NotImplementedError
                break
            except Exception as e:
                if not issubclass(type(e), (ConnectionError, TimeoutError)):
                    logging.warning('{0} {1} {2}'.format(type(e), e, traceback.format_exc()))
                self.close()
                await self._connector_ready()
            await asyncio.sleep(0.2)

        # do something
        assert recv_buffer is not None
        try:
            await self.data_received(recv_buffer)
        except Exception as e:
            if not issubclass(type(e), (ConnectionError, TimeoutError)):
                logging.warning('{0} {1} {2}'.format(type(e), e, traceback.format_exc()))
            pass

        # ready for next polling
        asyncio.ensure_future(self._server_polling())

    async def write(self, send_buffer):
        while True:
            try:
                self._server_writer.write(send_buffer)
                await self._server_writer.drain()
                break
            except Exception as e:
                if not issubclass(type(e), (ConnectionError, TimeoutError)):
                    logging.warning('{0} {1} {2}'.format(type(e), e, traceback.format_exc()))
                self.close()
                await self._connector_ready()
            await asyncio.sleep(0.2)

    async def data_received(self, recv_buffer):
        raise NotImplementedError


class SharedConnector(StableConnector):
    def __init__(self):
        StableConnector.__init__(self)
        #
        self._table = dict()

    def register_handler_cb(self, handler_id, received_cb):
        self._table[handler_id] = received_cb

    def unregister_handler_cb(self, handler_id):
        del self._table[handler_id]

    async def feed(self, handler_id, send_buffer):
        if handler_id not in self._table:
            raise RuntimeError
        send_buffer = struct.pack('Q', handler_id) + send_buffer
        await self.write(send_buffer)

    async def data_received(self, recv_buffer):
        handler_id, recv_buffer = struct.unpack('Q', recv_buffer[:8]), recv_buffer[8:]
        if handler_id not in self._table:
            logging.warning('handler_id not in self._table')
            return
        received_cb = self._table[handler_id]
        await received_cb(recv_buffer)


class LocalHandlerBase(TimeoutHandler, asyncio.Protocol):
    def __init__(self):
        TimeoutHandler.__init__(self)
        #
        self._closed = False
        #
        self.local_transport = None
        self.local_peername = None

    def is_alive(self):
        return not self._closed

    def close(self):
        # once we `call transport.close()`, a flag in transport set from `closing` to  `closed`
        if self.local_transport is not None:
            self.local_transport.close()
        self._closed = True

    def connection_made(self, transport):
        self.keep_alive_open()
        self.local_transport = transport
        self.local_peername = transport.get_extra_info('peername')

    def data_received(self, data):
        self.keep_alive_active()
        coro = self.local_data_received(data)
        asyncio.ensure_future(coro)

    def connection_lost(self, exc):
        self.close()

    async def local_data_received(self, recv_buffer):
        raise NotImplementedError

    async def client_data_received(self, recv_buffer):
        raise NotImplementedError


class LocalHandler(LocalHandlerBase):
    STAGE_DESTROY, STAGE_INIT, STAGE_CONNECT, STAGE_STREAM = -1, 0, 1, 2

    def __init__(self, shared_connector):
        LocalHandlerBase.__init__(self)
        self._stage = self.STAGE_DESTROY
        self._shared_connector = shared_connector
        self._shared_connector.register_handler_cb(id(self), self.client_data_received)

    def __del__(self):
        self._shared_connector.unregister_handler_cb(id(self))

    async def local_data_received(self, recv_buffer):
        if self._stage == self.STAGE_INIT:
            (ver, n_methods), methods = struct.unpack('BB', recv_buffer[:2]), recv_buffer[2:]
            if ver == 5 and n_methods == 1 and methods == b'\x00':
                self._stage = self.STAGE_CONNECT
                send_buffer = struct.pack('BB', 5, 0)
                self.local_transport.write(send_buffer)
            else:
                self.close()

        elif self._stage == self.STAGE_CONNECT:
            raise NotImplementedError

        elif self._stage == self.STAGE_STREAM:
            await self._shared_connector.feed(id(self), recv_buffer)

        else:
            raise NotImplementedError

    async def client_data_received(self, recv_buffer):
        pass


def exception_handler(loop, context):
    assert loop is not None
    exception = context['exception']
    if issubclass(type(exception), (ConnectionError, TimeoutError)):
        pass
    else:
        logging.error('{0} {1} {2}'.format(type(exception), context, traceback.format_exc()))


def main():
    loop = asyncio.get_event_loop()
    # loop.set_exception_handler(exception_handler)
    shared_connector = SharedConnector()
    coro = loop.create_server(lambda: LocalHandler(shared_connector), '127.0.0.1', 1081)
    server = loop.run_until_complete(coro)

    logging.info('Serving on {}'.format(server.sockets[0].getsockname()))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    server.close()
    loop.run_until_complete(server.wait_closed())
    loop.close()


def init_logging():
    handler = logging.StreamHandler()
    logging.basicConfig(handlers=[handler],
                        format='[%(levelname)s] %(asctime)s - %(funcName)s() - %(message)s',
                        level=logging.DEBUG)


if __name__ == '__main__':
    init_logging()
    main()
