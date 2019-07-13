import os
import time
import random
import struct
import asyncio
import logging
import traceback
from base import BaseProtocol


class RemoteTCP(BaseProtocol):
    def __init__(self, server, connection_id):
        BaseProtocol.__init__(self, [self.remote_connection_made,
                                     self.remote_data_received,
                                     self.remote_connection_lost])
        self._server = server
        self._connection_id = connection_id

    def remote_connection_made(self):
        logging.debug('remote_connection_made: {}'.format(self._peername))
        self._server.remote_connection_made(self._connection_id, self)

    def remote_data_received(self, recv_buffer):
        self._server.remote_data_received(self._connection_id, recv_buffer)

    def remote_connection_lost(self, exc):
        logging.debug('remote_connection_lost: {}'.format(self._peername))
        self._server.remote_connection_lost(self._connection_id)

    def server_data_received(self, recv_buffer):
        self.write(recv_buffer)


class ServerProtocol(BaseProtocol):
    # connection_id, len_payload, payload
    HEADER_LEN = 8
    MIN_BUFSIZE = HEADER_LEN

    def __init__(self, loop=None):
        BaseProtocol.__init__(self, [self.server_connection_made,
                                     self.server_data_received,
                                     self.server_connection_lost], statistic=True)
        self._loop = loop or asyncio.get_event_loop()
        # connection_id -> remote
        self._table = dict()
        self._recv_buffer = b''
    
    def server_connection_made(self):
        logging.debug('server_connection_made: {}'.format(self._peername))
    
    def server_data_received(self, data):
        # unpack data
        self._recv_buffer += data
        while len(self._recv_buffer) >= self.MIN_BUFSIZE:
            # unpack payload
            connection_id, len_payload = struct.unpack('!II', self._recv_buffer[:self.HEADER_LEN])
            if len(self._recv_buffer) < (self.HEADER_LEN + len_payload):
                break
            payload = self._recv_buffer[self.HEADER_LEN:self.HEADER_LEN + len_payload]
            self._recv_buffer = self._recv_buffer[self.HEADER_LEN + len_payload:]
            # handle payload
            if connection_id in self._table:
                # existing connection
                remote = self._table[connection_id]
                if len_payload == 0:
                    logging.debug('len_payload == 0: {}'.format(self._peername))
                    del self._table[connection_id]
                    remote.close()
                else:
                    remote.server_data_received(payload)
            else:
                # new conection
                asyncio.ensure_future(self._create_new_remote(connection_id, payload))

    async def _create_new_remote(self, connection_id, payload):
        if len(payload) < 5:
            logging.debug('unexpected data, maybe remote closed before local, instance_id: {0}, recv_buffer: {1}'.format(connection_id, payload))
            return
        # parse socks5
        (ver, cmd, rsv, atype, len_addr), dst_addr, (dst_port,) = struct.unpack('!BBBBB', payload[:5]), \
                                                                payload[5:-2], \
                                                                struct.unpack('!H', payload[-2:])
        if ver == 5 and cmd == 1 and rsv == 0 and len_addr == len(dst_addr):
            rep, atype, bind_addr, bind_port = None, None, None, None
            try:
                await self._loop.create_connection(lambda: RemoteTCP(self, connection_id), dst_addr, dst_port)
            except Exception as e:
                if not issubclass(type(e), (TimeoutError, ConnectionError, OSError, IOError)):
                    logging.info('{} {} {}'.format(type(e), e, traceback.format_exc()))
                rep, atype, bind_addr, bind_port = 4, 1, 0, 0
            else:
                rep, atype, bind_addr, bind_port = 0, 1, 0, 0
            finally:
                send_buffer = struct.pack('!IIBBBBIH', connection_id, 10, ver, rep, rsv, atype, bind_addr, bind_port)
                self.write(send_buffer)
        else:
            logging.debug('unexpected data, maybe remote closed before local, instance_id: {0}, recv_buffer: {1}'.format(connection_id, payload))

    def server_connection_lost(self, exc):
        logging.debug('server_connection_lost: {}'.format(self._peername))
        raise NotImplementedError
    
    def remote_connection_made(self, connection_id, remote):
        assert connection_id not in self._table
        self._table[connection_id] = remote
    
    def remote_data_received(self, connection_id, data):
        send_buffer = struct.pack('!II', connection_id, len(data)) + data
        self.write(send_buffer)
    
    def remote_connection_lost(self, connection_id):
        if connection_id not in self._table:
            return
        del self._table[connection_id]
        # send close notice
        send_buffer = struct.pack('!II', connection_id, 0)
        self.write(send_buffer)


def main():
    loop = asyncio.get_event_loop()
    coro = loop.create_server(ServerProtocol, '127.0.0.1', 1521)
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
                        level=logging.INFO)


if __name__ == '__main__':
    init_logging()
    main()
