import time
import struct
import asyncio
import logging
import traceback

config = {'server_addr': '127.0.0.1',
          'server_port': 1521,
          'local_addr': '127.0.0.1',
          'local_port': 1081}


class TimeoutHandler:
    def __init__(self):
        self._last_active_time = time.time()
        self._timeout_seconds = 20.0

    def is_alive(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def keep_alive_open(self):
        asyncio.ensure_future(self._keep_alive())

    def keep_alive_active(self):
        self._last_active_time = time.time()

    def _timer_triggered(self):
        self.close()

    async def _keep_alive(self):
        while self.is_alive():
            current_time = time.time()
            if (current_time - self._last_active_time) > self._timeout_seconds:
                self._timer_triggered()
                return
            else:
                if current_time < self._last_active_time:  # system time reset
                    self.keep_alive_active()
                await asyncio.sleep(2.0)


class LocalHandler(TimeoutHandler):
    MAX_SIZE = 64 * 1024
    STAGE_DESTROY, STAGE_INIT, STAGE_CONNECT, STAGE_STREAM = -1, 0, 1, 2

    def __init__(self):
        TimeoutHandler.__init__(self)
        #
        self._local_transport = None
        self._local_peername = None
        self._local_reader = None
        self._local_writer = None
        #
        self._client_transport = None
        self._client_peername = None
        self._client_reader = None
        self._client_writer = None
        #
        self._stage = self.STAGE_DESTROY
        self._send_queue = asyncio.Queue()

    def is_alive(self):
        if self._local_transport is None or self._local_transport.is_closing():
            return False
        elif self._client_transport is None or self._client_transport.is_closing():
            return False
        else:
            return True

    def close(self):
        # once we `call transport.close()`, a flag in transport set from `closing` to  `closed`
        if self._local_transport is not None:
            self._local_transport.close()
            self._local_transport = None
        if self._client_transport is not None:
            self._client_transport.close()
            self._client_transport = None

    def accept_local(self, client_transport, client_reader, client_writer):
        self.keep_alive_open()
        self._stage = self.STAGE_INIT
        #
        self._local_transport = client_transport
        self._local_peername = client_transport.get_extra_info('peername')
        self._local_reader = client_reader
        self._local_writer = client_writer
        #
        asyncio.ensure_future(self._local_polling())

    async def _local_polling(self):
        try:
            recv_buffer = await self._local_reader.read(self.MAX_SIZE)
        except Exception as e:
            if not issubclass(type(e), (ConnectionError, TimeoutError)):
                logging.warning('{0} {1} {2}'.format(type(e), e, traceback.format_exc()))
            self.close()
            return

        # if client close connection, the `reader.at_eof()` returns True, we thing connection is closed
        if len(recv_buffer) == 0:  # and self._local_reader.at_eof():
            self.close()
            return

        # do something
        self.keep_alive_active()
        assert recv_buffer is not None
        try:
            await self.local_data_received(recv_buffer)
        except Exception as e:
            if not issubclass(type(e), (ConnectionError, TimeoutError)):
                logging.warning('{0} {1} {2}'.format(type(e), e, traceback.format_exc()))
            self.close()
            return

        # ready for next polling
        asyncio.ensure_future(self._local_polling())

    async def _client_polling(self):
        try:
            recv_buffer = await self._client_reader.read(self.MAX_SIZE)
        except Exception as e:
            if not issubclass(type(e), (ConnectionError, TimeoutError)):
                logging.warning('{0} {1} {2}'.format(type(e), e, traceback.format_exc()))
            self.close()
            return

        # if client close connection, the `reader.at_eof()` returns True, we thing connection is closed
        if len(recv_buffer) == 0:  # and self._client_reader.at_eof():
            self.close()
            return

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

    async def _client_sending(self):
        pass

    async def local_data_received(self, recv_buffer):
        pass

    async def client_data_received(self, recv_buffer):
        pass


def exception_handler(loop, context):
    assert loop is not None
    exception = context['exception']
    if issubclass(type(exception), (ConnectionError, TimeoutError)):
        pass
    else:
        logging.error('{0} {1} {2}'.format(type(exception), context, traceback.format_exc()))


def local_connected_cb(local_reader, local_writer):
    transport = local_writer.transport
    # apply handler
    handler = LocalHandler()
    handler.accept_local(transport, local_reader, local_writer)


def main():
    loop = asyncio.get_event_loop()
    # loop.set_exception_handler(exception_handler)
    coro = asyncio.start_server(local_connected_cb, config['local_addr'], config['local_port'])
    local = loop.run_until_complete(coro)

    logging.info('Listening on {}'.format(local.sockets[0].getsockname()))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    local.close()
    loop.run_until_complete(local.wait_closed())
    loop.close()


def init_logging():
    handler = logging.StreamHandler()
    logging.basicConfig(handlers=[handler],
                        format='[%(levelname)s] %(asctime)s - %(funcName)s() - %(message)s',
                        level=logging.DEBUG)


if __name__ == '__main__':
    init_logging()
    main()
