import time
import struct
import socket
import asyncio
import logging
import traceback
from utils import TimeoutHandler, ServerProtocol, RemoteProtocol


class RemoteHandler(TimeoutHandler, RemoteProtocol):
    def __init__(self, h_server, connection_id):
        TimeoutHandler.__init__(self)
        #
        self._server = h_server
        self._connection_id = connection_id
        self._remote_transport = None
        self._remote_peername = None

    # ----------------------------------------------
    # -----------TimeoutHandler overridden----------
    # ----------------------------------------------
    def is_alive(self):
        if self._remote_transport is None:
            return False
        elif self._remote_transport.is_closing():
            return False
        else:
            return True

    def close(self):
        if self.is_alive():
            self._remote_transport.close()

    # ----------------------------------------------
    # -----------RemoteHandler overridden-----------
    # ----------------------------------------------
    def remote_connection_made(self, transport):
        self._remote_transport = transport
        self._remote_peername = transport.get_extra_info('peername')
        self._server.register_handler(self._connection_id, self)

    def remote_data_received(self, recv_buffer):
        self._server.remote_data_received(self._connection_id, recv_buffer)

    def remote_connection_lost(self, exc):
        self._server.unregister_handler(self._connection_id)

    def server_data_received(self, recv_buffer):
        self._remote_transport.write(recv_buffer)


class ServerHandler(TimeoutHandler, ServerProtocol):
    HEADER_LEN = 8

    def __init__(self, loop=None):
        TimeoutHandler.__init__(self)
        #
        self._loop = loop or asyncio.get_event_loop()
        self._client_transport = None
        self._client_peername = None
        #
        self._table = dict()
        self._recv_buffer = b''

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
        self._client_transport = transport
        self._client_peername = transport.get_extra_info('peername')

    def client_data_received(self, data):
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
            # 3. check id
            coro = self._handle_connect_or_stream(connection_id, payload)
            asyncio.ensure_future(coro)

    async def _handle_connect_or_stream(self, connection_id, payload):
        if connection_id in self._table:
            remote = self._table[connection_id]
            if len(payload) == 0:
                remote.close()
            else:
                remote.server_data_received(payload)
        else:
            # remote closed before local
            if len(payload) == 0:
                return
            # new connection
            (ver, cmd, rsv, atype, len_addr), dst_addr, (dst_port,) = struct.unpack('=BBBBB', payload[:5]), \
                                                                      payload[5:-2], \
                                                                      struct.unpack('!H', payload[-2:])
            if ver == 5 and cmd == 1 and rsv == 0 and len_addr == len(dst_addr):
                logging.debug('STAGE_CONNECTION instance_id: {0}, dst: {1}'.format(connection_id, (dst_addr, dst_port)))
                rep, atype, bind_addr, bind_port = None, None, None, None
                try:
                    await self._loop.create_connection(lambda: RemoteHandler(self, connection_id), dst_addr, dst_port)
                except Exception as e:
                    if not issubclass(type(e), (TimeoutError, ConnectionError, OSError, IOError)):
                        logging.warning('{} {} {}'.format(type(e), e, traceback.format_exc()))
                    rep, atype, bind_addr, bind_port = 4, 1, 0, 0
                else:
                    rep, atype, bind_addr, bind_port = 0, 1, 0, 0
                finally:
                    send_buffer = struct.pack('=IIBBBBIH', connection_id, 10, ver, rep, rsv, atype, bind_addr, bind_port)
                    self._client_transport.write(send_buffer)
            else:
                logging.debug('unexpected data, maybe remote closed before local, instance_id: {0}, recv_buffer: {1}'.format(connection_id, payload))

    def client_connection_lost(self, exc):
        pass

    def remote_data_received(self, connection_id, data):
        self.keep_alive_active()
        send_buffer = struct.pack('=II', connection_id, len(data)) + data
        self._client_transport.write(send_buffer)

    # ----------------------------------------------
    # ----------------ServerHandler-----------------
    # ----------------------------------------------
    def register_handler(self, connection_id, remote):
        self._table[connection_id] = remote

    def unregister_handler(self, connection_id):
        send_buffer = struct.pack('=II', connection_id, 0)
        self._client_transport.write(send_buffer)
        del self._table[connection_id]


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
