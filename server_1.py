import time
import struct
import asyncio
import logging
import traceback
from utils import TimeoutHandler, ServerProtocol


class ServerHandler(TimeoutHandler, ServerProtocol):
    def __init__(self):
        TimeoutHandler.__init__(self)
        self._client_transport = None
        self._client_peername = None

    # ----------------------------------------------
    # -----------TimeoutHandler overridden----------
    # ----------------------------------------------
    def is_alive(self):
        if self._client_transport is None:
            return False
        elif self._client_transport.is_closing():
            return False
        else:
            return True

    def close(self):
        if self.is_alive():
            self._client_transport.close()

    # ----------------------------------------------
    # -----------ServerHandler overridden-----------
    # ----------------------------------------------
    def client_connection_made(self, transport):
        raise NotImplementedError

    def client_data_received(self, data):
        raise NotImplementedError

    def client_connection_lost(self, exc):
        raise NotImplementedError

    def remote_data_received(self, data):
        raise NotImplementedError


def main():
    loop = asyncio.get_event_loop()
    coro = loop.create_server(ServerHandler, '127.0.0.1', 1521)
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
