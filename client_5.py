import os
import time
import queue
import random
import struct
import asyncio
import logging
from base import BaseProtocol


class MRU:
    SIZE_LIMIT = 512

    def __init__(self):
        self._table = dict()
        self._queue = queue.Queue()
    
    def __contains__(self, key):
        return key in self._table
    
    def __getitem__(self, key):
        return self._table[key]
    
    def __setitem__(self, key, value):
        while self._queue.qsize() > self.SIZE_LIMIT:
            oldest = self._queue.get()
            del self._table[oldest]
        self._queue.put(key)
        self._table[key] = value
        assert len(self._table) <= self.SIZE_LIMIT


class ClientProtocol(BaseProtocol):
    # connection_id, len_payload, payload
    HEADER_LEN = 8
    MIN_BUFSIZE = HEADER_LEN

    def __init__(self):
        BaseProtocol.__init__(self, [self.client_connection_made,
                                     self.client_data_received,
                                     self.client_connection_lost], statistic=True)
        # connection_id -> client_data_handler
        self._table = dict()
        self._recv_buffer = b''
        self._mru = MRU()
        #
        loop = asyncio.get_event_loop()
        coro = loop.create_connection(lambda: self, '127.0.0.1', 1521)
        asyncio.ensure_future(coro)
    
    def client_connection_made(self):
        logging.debug('client_connection_made: {}'.format(self._peername))
    
    def client_data_received(self, data):
        self._recv_buffer += data
        while len(self._recv_buffer) >= self.MIN_BUFSIZE:
            # unpack payload
            connection_id, len_payload = struct.unpack('!II', self._recv_buffer[:self.HEADER_LEN])
            if len(self._recv_buffer) < (self.HEADER_LEN + len_payload):
                break
            payload = self._recv_buffer[self.HEADER_LEN:self.HEADER_LEN + len_payload]
            self._recv_buffer = self._recv_buffer[self.HEADER_LEN + len_payload:]
            # handle connection closed
            if connection_id not in self._table:
                return
            local = self._table[connection_id]
            if len_payload == 0:
                logging.debug('len_payload == 0: {}'.format(self._peername))
                del self._table[connection_id]  # remove handler explicit
                local.close()
                return
            # handle payload
            local.client_data_received(payload)
    
    def client_connection_lost(self, exc):
        logging.debug('client_connection_lost: {}'.format(self._peername))
        raise NotImplementedError

    def local_connection_made(self, local):
        # return a unique id
        while True:
            connection_id = random.randrange(0xFFFFFFFF)
            if connection_id in self._mru:
                continue
            if connection_id in self._table:
                continue
            self._table[connection_id] = local
            return connection_id
    
    def local_data_received(self, connection_id, send_buffer):
        send_buffer = struct.pack('!II', connection_id, len(send_buffer)) + send_buffer
        self.write(send_buffer)
    
    def local_connection_lost(self, connection_id):
        if connection_id not in self._table:
            return
        del self._table[connection_id]
        # send close notice
        send_buffer = struct.pack('!II', connection_id, 0)
        self.write(send_buffer)


class LocalSocks5(BaseProtocol):
    STAGE_DESTROY, STAGE_INIT, STAGE_CONNECT, STAGE_STREAM = -1, 0, 1, 2

    def __init__(self, client):
        BaseProtocol.__init__(self, [self.local_connection_made,
                                     self.local_data_received,
                                     self.local_connection_lost])
        self._stage = self.STAGE_DESTROY
        self._client = client
        self._connection_id = None
    
    def local_connection_made(self):
        logging.debug('local_connection_made: {}'.format(self._peername))
        self._stage = self.STAGE_INIT
        self._connection_id = self._client.local_connection_made(self)
    
    def local_data_received(self, data):
        if self._stage == self.STAGE_INIT:
            (ver, n_methods), methods = struct.unpack('!BB', data[:2]), data[2:]
            if ver == 5 and n_methods == 1 and methods == b'\x00':
                self._stage = self.STAGE_CONNECT
                send_buffer = struct.pack('!BB', 5, 0)
                self.write(send_buffer)
            else:
                logging.warning('unexpected data, stage: {0}, recv_buffer: {1}'.format(self._stage, data))
                self.close()
        elif self._stage == self.STAGE_CONNECT:
            # server handle this stage
            self._client.local_data_received(self._connection_id, data)
        elif self._stage == self.STAGE_STREAM:
            # relay stream
            self._client.local_data_received(self._connection_id, data)
        else:
            raise RuntimeError
    
    def client_data_received(self, data):
        if self._stage == self.STAGE_CONNECT:
            self._stage = self.STAGE_STREAM
            self.write(data)
        elif self._stage == self.STAGE_STREAM:
            self.write(data)
    
    def local_connection_lost(self, exc):
        logging.debug('local_connection_lost: {}'.format(self._peername))
        self._client.local_connection_lost(self._connection_id)


def main():
    client = ClientProtocol()

    loop = asyncio.get_event_loop()
    coro = loop.create_server(lambda: LocalSocks5(client), '127.0.0.1', 1081)
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
