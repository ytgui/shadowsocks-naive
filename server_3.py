import time
import struct
import socket
import asyncio
import logging
import traceback
from utils import TimeoutHandler, ServerProtocol, RemoteProtocol


class RemoteHandler(TimeoutHandler, RemoteProtocol):
    def __init__(self, h_server, instance_id):
        TimeoutHandler.__init__(self)
        #
        self._server = h_server
        self._instance_id = instance_id
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
        self._server.register_handler(self._instance_id, self.server_data_received)

    def remote_data_received(self, recv_buffer):
        self._server.remote_data_received(self._instance_id, recv_buffer)

    def remote_connection_lost(self, exc):
        self._server.unregister_handler(self._instance_id)

    def server_data_received(self, recv_buffer):
        self._remote_transport.write(recv_buffer)


class ServerHandler(TimeoutHandler, ServerProtocol):
    def __init__(self, loop=None):
        TimeoutHandler.__init__(self)
        #
        self._loop = loop or asyncio.get_event_loop()
        self._client_transport = None
        self._client_peername = None
        #
        self._table = dict()

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

    async def client_data_received(self, recv_buffer):
        while len(recv_buffer) >= 10:
            (instance_id, len_payload), recv_buffer = struct.unpack('=QH', recv_buffer[:10]), recv_buffer[10:]
            if len(recv_buffer) < len_payload:
                logging.warning('len(recv_buffer) < len_payload')
                return
            if len_payload == 0:
                pass
            payload, recv_buffer = recv_buffer[:len_payload], recv_buffer[len_payload:]
            await self._handle_connect_or_stream(instance_id, payload)
        else:
            if len(recv_buffer) != 0:
                logging.warning('unexpected length of recv_buffer')

    async def _handle_connect_or_stream(self, instance_id, payload):
        if instance_id in self._table:  # STAGE_STREAM
            remote_cb = self._table[instance_id]
            remote_cb(payload)
        else:  # STAGE_CONNECT
            (ver, cmd, rsv, atype, len_addr), dst_addr, (dst_port,) = struct.unpack('=BBBBB', payload[:5]), \
                                                                      payload[5:-2], \
                                                                      struct.unpack('!H', payload[-2:])
            if ver == 5 and cmd == 1 and rsv == 0 and len_addr == len(dst_addr):
                logging.debug('STAGE_CONNECTION instance_id: {0}, dst: {1}'.format(instance_id, (dst_addr, dst_port)))
                rep, atype, bind_addr, bind_port = None, None, None, None
                try:
                    await self._loop.create_connection(lambda: RemoteHandler(self, instance_id), dst_addr, dst_port)
                except Exception as e:
                    if not issubclass(type(e), (TimeoutError, ConnectionError, OSError, IOError)):
                        logging.warning('{} {} {}'.format(type(e), e, traceback.format_exc()))
                    rep, atype, bind_addr, bind_port = 4, 1, 0, 0
                else:
                    rep, atype, bind_addr, bind_port = 0, 1, 0, 0
                finally:
                    send_buffer = struct.pack('=QHBBBBIH', instance_id, 10, ver, rep, rsv, atype, bind_addr, bind_port)
                    self._client_transport.write(send_buffer)
            else:
                logging.debug('unexpected data, instance_id: {0}, recv_buffer: {1}'.format(instance_id, payload))

    def client_connection_lost(self, exc):
        pass

    def remote_data_received(self, instance_id, recv_buffer):
        self.keep_alive_active()
        recv_buffer = struct.pack('=QH', instance_id, len(recv_buffer)) + recv_buffer
        self._client_transport.write(recv_buffer)

    # ----------------------------------------------
    # ----------------ServerHandler-----------------
    # ----------------------------------------------
    def register_handler(self, instance_id, instance_cb):
        self._table[instance_id] = instance_cb

    def unregister_handler(self, instance_id):
        recv_buffer = struct.pack('=QH', instance_id, 0)
        self._client_transport.write(recv_buffer)
        del self._table[instance_id]


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
