import time
import random
import struct
import asyncio
import logging
import traceback
from utils import TimeoutHandler, LocalProtocol, ClientProtocol


class ClientHandler(TimeoutHandler, ClientProtocol):
    HEADER_LEN = 8

    def __init__(self):
        TimeoutHandler.__init__(self)
        #
        self._loop = asyncio.get_event_loop()
        self._server_transport = None
        self._server_peername = None
        #
        self._table = dict()
        self._recv_buffer = b''
        #
        loop = asyncio.get_event_loop()
        coro = loop.create_connection(lambda: self, '127.0.0.1', 1521)
        asyncio.ensure_future(coro)

    # ----------------------------------------------
    # -----------TimeoutHandler overridden----------
    # ----------------------------------------------
    def is_alive(self):
        if self._server_transport is None:
            return False
        elif self._server_transport.is_closing():
            return False
        else:
            return True

    def close(self):
        if self.is_alive():
            self._server_transport.close()

    # ----------------------------------------------
    # -----------ClientProtocol overridden----------
    # ----------------------------------------------
    def server_connection_made(self, transport):
        self._server_transport = transport
        self._server_peername = transport.get_extra_info('peername')

    def server_data_received(self, data):
        self._recv_buffer += data
        while len(self._recv_buffer) >= self.HEADER_LEN:
            connection_id, len_payload = struct.unpack('=II', self._recv_buffer[:self.HEADER_LEN])
            # 1. check package finish
            if len(self._recv_buffer) < len_payload + self.HEADER_LEN:
                # wait next package
                break
            # 2. re-allocate buffer
            payload = self._recv_buffer[self.HEADER_LEN:self.HEADER_LEN + len_payload]
            self._recv_buffer = self._recv_buffer[self.HEADER_LEN + len_payload:]
            # 3. check id, this happening if local closed before remote
            if connection_id not in self._table:
                if len_payload != 0:
                    logging.warning('connection_id not in table: {}'.format(connection_id))
                continue
            local = self._table[connection_id]
            # 4. connection closed
            if len_payload == 0:
                local.close()
                continue
            # 5. relay stream
            local.client_data_received(payload)

    def server_connection_lost(self, exc):
        raise NotImplementedError

    def local_data_received(self, connection_id, send_buffer):
        if connection_id not in self._table:
            raise RuntimeError
        send_buffer = struct.pack('=II', connection_id, len(send_buffer)) + send_buffer
        self._server_transport.write(send_buffer)

    # ----------------------------------------------
    # ----------------ClientHandler-----------------
    # ----------------------------------------------
    def register_local(self, local):
        while True:
            connection_id = random.randrange(0xFFFF_FFFF)
            if connection_id in self._table:
                continue
            self._table[connection_id] = local
            return connection_id

    def unregister_local(self, connection_id):
        # send (connection_id, 0, b'') to indicate this connection is closed
        send_buffer = struct.pack('=II', connection_id, 0)
        self._server_transport.write(send_buffer)
        del self._table[connection_id]


class LocalHandler(TimeoutHandler, LocalProtocol):
    STAGE_DESTROY, STAGE_INIT, STAGE_CONNECT, STAGE_STREAM = -1, 0, 1, 2

    def __init__(self, h_client):
        TimeoutHandler.__init__(self)
        #
        self._stage = self.STAGE_DESTROY
        self._local_transport = None
        self._local_peername = None
        #
        self._client = h_client
        self._connection_id = None

    # ----------------------------------------------
    # -----------TimeoutHandler overridden----------
    # ----------------------------------------------
    def is_alive(self):
        if self._local_transport is None:
            return False
        elif self._local_transport.is_closing():
            return False
        else:
            return True

    def close(self):
        # once we `call transport.close()`, a flag in transport set from `closing` to  `closed`
        if self.is_alive():
            self._local_transport.close()

    # ----------------------------------------------
    # ----------LocalProtocol overridden------------
    # ----------------------------------------------
    def local_connection_made(self, transport):
        self.keep_alive_open()
        self._stage = self.STAGE_INIT
        self._local_transport = transport
        self._local_peername = transport.get_extra_info('peername')
        self._connection_id = self._client.register_local(self)

    def local_data_received(self, data):
        self.keep_alive_active()
        if self._stage == self.STAGE_INIT:
            (ver, n_methods), methods = struct.unpack('=BB', data[:2]), data[2:]
            if ver == 5 and n_methods == 1 and methods == b'\x00':
                self._stage = self.STAGE_CONNECT
                send_buffer = struct.pack('=BB', 5, 0)
                self._local_transport.write(send_buffer)
            else:
                logging.warning('unexpected data, stage: {0}, recv_buffer: {1}'.format(self._stage, data))
                self.close()

        elif self._stage == self.STAGE_CONNECT:
            # do something such as redirect traffic in this place
            self._client.local_data_received(self._connection_id, data)

        elif self._stage == self.STAGE_STREAM:
            # relay stream
            self._client.local_data_received(self._connection_id, data)

        else:
            raise NotImplementedError

    def local_connection_lost(self, exc):
        self._client.unregister_local(self._connection_id)

    def client_data_received(self, data):
        self.keep_alive_active()
        if self._stage == self.STAGE_CONNECT:
            self._stage = self.STAGE_STREAM
            self._local_transport.write(data)

        elif self._stage == self.STAGE_STREAM:
            self._local_transport.write(data)

        else:
            raise NotImplementedError


def main():
    loop = asyncio.get_event_loop()
    h_client = ClientHandler()
    coro = loop.create_server(lambda: LocalHandler(h_client), '127.0.0.1', 1081)
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
