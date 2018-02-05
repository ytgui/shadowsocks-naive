import time
import struct
import asyncio
import logging
import traceback

config = {}


class TimeoutHandler:
    def __init__(self):
        self._last_active_time = time.time()
        self._timeout_seconds = 20

    def is_alive(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def keep_alive_open(self):
        asyncio.ensure_future(self._keep_alive())

    def keep_alive_active(self):
        self._last_active_time = time.time()

    async def _keep_alive(self):
        while self.is_alive():
            current_time = time.time()
            if (current_time - self._last_active_time) > self._timeout_seconds:
                self.close()
                break
            else:
                if current_time < self._last_active_time:  # system time reset
                    self.keep_alive_active()
                await asyncio.sleep(2.0)


class ClientHandler(TimeoutHandler):
    MAX_SIZE = 64 * 1024
    STAGE_DESTROY, STAGE_INIT, STAGE_CONNECT, STAGE_STREAM = -1, 0, 1, 2

    def __init__(self):
        TimeoutHandler.__init__(self)
        #
        self._closed = False
        #
        self._client_transport = None
        self._client_peername = None
        self._client_reader = None
        self._client_writer = None
        #
        self._remote_transport = None
        self._remote_peername = None
        self._remote_reader = None
        self._remote_writer = None
        #
        self._stage = self.STAGE_DESTROY

    def is_alive(self):
        return not self._closed

    def close(self):
        # once we `call transport.close()`, a flag in transport set from `closing` to  `closed`
        if self._client_transport is not None:
            self._client_transport.close()
        if self._remote_transport is not None:
            self._remote_transport.close()
        self._closed = True

    def accept_client(self, client_transport, client_reader, client_writer):
        self.keep_alive_open()
        self._stage = self.STAGE_INIT
        #
        self._client_transport = client_transport
        self._client_peername = client_transport.get_extra_info('peername')
        self._client_reader = client_reader
        self._client_writer = client_writer
        #
        asyncio.ensure_future(self._client_polling())

    async def _client_polling(self):
        try:
            recv_buffer = await self._client_reader.read(self.MAX_SIZE)
        except Exception as e:
            if not issubclass(type(e), (ConnectionError, TimeoutError)):
                logging.warning('{0} {1} {2}'.format(type(e), e, traceback.format_exc()))
            self.close()
            return

        # if client close connection, the `reader.at_eof()` returns True, we thing connection is closed
        if len(recv_buffer) == 0 and self._client_reader.at_eof():
            self.close()
            return

        if self._client_reader.at_eof():
            if len(recv_buffer) != 0:
                raise NotImplementedError

        # do something
        self.keep_alive_active()
        assert recv_buffer is not None
        try:
            await self.client_data_received(recv_buffer)
        except Exception as e:
            if not issubclass(type(e), (ConnectionError, TimeoutError)):
                logging.warning('{0} {1} {2}'.format(type(e), e, traceback.format_exc()))
            self.close()
            return

        # ready for next polling
        asyncio.ensure_future(self._client_polling())

    async def _remote_polling(self):
        try:
            recv_buffer = await self._remote_reader.read(self.MAX_SIZE)
        except Exception as e:
            if not issubclass(type(e), (ConnectionError, TimeoutError)):
                logging.warning('{0} {1} {2}'.format(type(e), e, traceback.format_exc()))
            self.close()
            return

        # if client close connection, the `reader.at_eof()` returns True, we thing connection is closed
        if len(recv_buffer) == 0 and self._remote_reader.at_eof():
            self.close()
            return

        # do something
        self.keep_alive_active()
        assert recv_buffer is not None
        try:
            await self.remote_data_received(recv_buffer)
        except Exception as e:
            if not issubclass(type(e), (ConnectionError, TimeoutError)):
                logging.warning('{0} {1} {2}'.format(type(e), e, traceback.format_exc()))
            self.close()
            return

        # ready for next polling
        asyncio.ensure_future(self._remote_polling())

    async def client_data_received(self, recv_buffer):
        if self._stage == self.STAGE_INIT:
            (ver, n_methods), methods = struct.unpack('BB', recv_buffer[:2]), recv_buffer[2:]
            if ver == 5 and n_methods == 1 and methods == b'\x00':
                self._stage = self.STAGE_CONNECT
                send_buffer = struct.pack('BB', 5, 0)
                self._client_writer.write(send_buffer)
                await self._client_writer.drain()
            else:
                self.close()

        elif self._stage == self.STAGE_CONNECT:
            (ver, cmd, rsv, atype, len_addr), dst_addr, (dst_port,) = struct.unpack('BBBBB', recv_buffer[:5]), \
                                                                      recv_buffer[5:-2], \
                                                                      struct.unpack('!H', recv_buffer[-2:])
            if ver == 5 and rsv == 0 and len_addr == len(dst_addr):
                self._stage = self.STAGE_STREAM
                rep, bind_addr, bind_port, close_flag = None, None, None, False
                try:
                    self._remote_reader, self._remote_writer = await asyncio.open_connection(dst_addr, dst_port)
                    self._remote_transport = self._remote_writer.transport
                    self._remote_peername = self._remote_transport.get_extra_info('peername')
                    asyncio.ensure_future(self._remote_polling())
                    # not fully implement
                    rep, atype, bind_addr, bind_port = 0, 1, 0, 0
                except Exception as e:
                    close_flag = True
                    rep, atype, bind_addr, bind_port = 4, 1, 0, 0
                    if issubclass(type(e), (ConnectionError, TimeoutError)):
                        pass
                    else:
                        logging.warning('{0} {1} {2}'.format(type(e), e, traceback.format_exc()))
                finally:
                    send_buffer = struct.pack('BBBBIH', ver, rep, rsv, atype, bind_addr, bind_port)
                    self._client_writer.write(send_buffer)
                    await self._client_writer.drain()
                    if close_flag is True:
                        self.close()
            else:
                self.close()

        elif self._stage == self.STAGE_STREAM:
            self._remote_writer.write(recv_buffer)

        else:
            raise NotImplementedError

    async def remote_data_received(self, recv_buffer):
        if self._stage == self.STAGE_STREAM:
            self._client_writer.write(recv_buffer)

        else:
            raise NotImplementedError


def exception_handler(loop, context):
    assert loop is not None
    exception = context['exception']
    if issubclass(type(exception), (ConnectionError, TimeoutError)):
        pass
    else:
        logging.error('{0} {1} {2}'.format(type(exception), context, traceback.format_exc()))


def client_connected_cb(client_reader, client_writer):
    transport = client_writer.transport
    transport.write(b'1')
    # apply handler
    handler = ClientHandler()
    handler.accept_client(transport, client_reader, client_writer)


def main():
    loop = asyncio.get_event_loop()
    # loop.set_exception_handler(exception_handler)
    coro = asyncio.start_server(client_connected_cb, '127.0.0.1', 1081)
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
