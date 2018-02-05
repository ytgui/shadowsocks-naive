import time
import struct
import asyncio
import logging
import traceback
from utils import TimeoutHandler, LocalProtocol, ClientProtocol


class ClientHandler(TimeoutHandler, ClientProtocol):
    def __init__(self):
        TimeoutHandler.__init__(self)
        #
        self._loop = asyncio.get_event_loop()
        self._server_transport = None
        self._server_peername = None
        #
        self._table = dict()
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

    def server_data_received(self, recv_buffer):
        backup = recv_buffer
        while len(recv_buffer) >= 10:
            (instance_id, len_payload), recv_buffer = struct.unpack('=QH', recv_buffer[:10]), recv_buffer[10:]
            if len(recv_buffer) < len_payload:
                logging.warning('len(recv_buffer) < len_payload')
                return
            if len_payload == 0:
                pass
            payload, recv_buffer = recv_buffer[:len_payload], recv_buffer[len_payload:]
            #
            if instance_id in self._table:
                local_cb = self._table[instance_id]
                local_cb(payload)
            else:
                logging.warning('instance_id not in table: {}'.format(instance_id))
        else:
            if len(recv_buffer) != 0:
                logging.warning('unexpected length of recv_buffer')

    def server_connection_lost(self, exc):
        raise NotImplementedError

    def local_data_received(self, instance_id, send_buffer):
        if instance_id not in self._table:
            raise RuntimeError
        send_buffer = struct.pack('=QH', instance_id, len(send_buffer)) + send_buffer
        self._server_transport.write(send_buffer)

    # ----------------------------------------------
    # ----------------ClientHandler-----------------
    # ----------------------------------------------
    def register_local(self, instance_id, instance_cb):
        self._table[instance_id] = instance_cb

    def unregister_local(self, instance_id):
        recv_buffer = struct.pack('=QH', instance_id, 0)
        self._server_transport.write(recv_buffer)
        del self._table[instance_id]


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
        self._client.register_local(id(self), self.client_data_received)

    def local_data_received(self, recv_buffer):
        self.keep_alive_active()
        if self._stage == self.STAGE_INIT:
            (ver, n_methods), methods = struct.unpack('=BB', recv_buffer[:2]), recv_buffer[2:]
            if ver == 5 and n_methods == 1 and methods == b'\x00':
                self._stage = self.STAGE_CONNECT
                send_buffer = struct.pack('=BB', 5, 0)
                self._local_transport.write(send_buffer)
            else:
                logging.warning('unexpected data, stage: {0}, recv_buffer: {1}'.format(self._stage, recv_buffer))
                self.close()

        elif self._stage == self.STAGE_CONNECT:
            self._client.local_data_received(id(self), recv_buffer)

        elif self._stage == self.STAGE_STREAM:
            self._client.local_data_received(id(self), recv_buffer)

        else:
            raise NotImplementedError

    def local_connection_lost(self, exc):
        self._client.unregister_local(id(self))

    def client_data_received(self, recv_buffer):
        self.keep_alive_active()
        if self._stage == self.STAGE_CONNECT:
            self._stage = self.STAGE_STREAM
            self._local_transport.write(recv_buffer)

        elif self._stage == self.STAGE_STREAM:
            self._local_transport.write(recv_buffer)

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
