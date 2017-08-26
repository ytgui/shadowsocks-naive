#
# Copyright (C) 2017  bosskwei

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import time
import random
import socket
import logging
import asyncio
import struct
from shadowsocks import shell, cryptor, protocol


# addr: followed rfc1928, 8.8.8.8, ::::, www.google.com
# peername: ip:port
# host: addr:port


class TimeoutHandler:
    def __init__(self):
        self._transport = None
        self._last_active_time = time.time()
        self._timeout_limit = 20

    def close(self):
        raise NotImplementedError

    def keep_alive_open(self):
        asyncio.ensure_future(self._keep_alive())

    def keep_alive_active(self):
        self._last_active_time = time.time()

    async def _keep_alive(self):
        while self._transport is not None:
            current_time = time.time()
            if current_time - self._last_active_time > self._timeout_limit:
                self.close()
                break
            else:
                await asyncio.sleep(1)


class RemoteTCP(asyncio.Protocol, TimeoutHandler):
    def __init__(self, addr, port, data, key, local):
        TimeoutHandler.__init__(self)
        self._logger = logging.getLogger('<RemoteTCP{0} {1}>'.format((addr, port), hex(id(self))))
        self._data = data
        self._local = local
        self._peername = None
        self._transport = None
        self._transport_type = protocol.TRANSPORT_TCP
        self._cryptor = cryptor.Cryptor(protocol.TRANSPORT_TCP, key)

    def write(self, data):
        if self._transport is not None:
            self._transport.write(data)

    def close(self):
        if self._transport is not None:
            self._transport.close()

    def connection_made(self, transport):
        self.keep_alive_open()
        self._transport = transport
        self._peername = self._transport.get_extra_info('peername')
        self._logger.debug('connection made, peername={}'.format(self._peername))
        self.write(self._data)

    def data_received(self, data):
        self.keep_alive_active()
        self._logger.debug('received len={}'.format(len(data)))
        data = self._cryptor.encrypt(data)
        self._local.write(data)

    def eof_received(self):
        self._logger.debug('eof received')

    def connection_lost(self, exc):
        self._logger.debug('lost exc={exc}'.format(exc=exc))
        if self._local is not None:
            self._local.close()


class RemoteUDP(asyncio.DatagramProtocol, TimeoutHandler):
    def __init__(self, addr, port, data, key, local):
        TimeoutHandler.__init__(self)
        self._logger = logging.getLogger('<RemoteUDP{0} {1}>'.format((addr, port), hex(id(self))))
        self._data = data
        self._local = local
        self._peername = None
        self._transport = None
        self._transport_type = protocol.TRANSPORT_UDP
        self._cryptor = cryptor.Cryptor(protocol.TRANSPORT_UDP, key)

    def write(self, data):
        if self._transport is not None:
            self._transport.sendto(data, self._peername)

    def close(self):
        if self._transport is not None:
            self._transport.close()

    def connection_made(self, transport):
        self.keep_alive_open()
        self._transport = transport
        self._peername = self._transport.get_extra_info('peername')
        self._logger.debug('connection made, peername={}'.format(self._peername))
        self.write(self._data)

    def connection_lost(self, exc):
        self._logger.debug('lost exc={exc}'.format(exc=exc))

    def datagram_received(self, data, peername):
        self.keep_alive_active()
        self._logger.debug('received len={}'.format(len(data)))
        assert self._peername == peername
        src_addr, src_port = peername
        aa = socket.inet_pton(socket.AF_INET, src_addr)
        data = b'\x01' + aa + struct.pack('!H', src_port) + data
        data = self._cryptor.encrypt(data)
        self._local.write(data)

    def error_received(self, exc):
        self._logger.debug('lost exc={exc}'.format(exc=exc))


class LocalHandler(TimeoutHandler):
    STAGE_DESTROY = -1
    STAGE_INIT = 0
    STAGE_CONNECT = 1
    STAGE_STREAM = 2
    STAGE_ERROR = 0xFF

    def __init__(self, key):
        TimeoutHandler.__init__(self)
        self._key = key
        self._stage = self.STAGE_DESTROY
        self._peername = None
        self._transport = None
        self._transport_protocol = None
        self._remote = None
        self._cryptor = None
        self._logger = None

    def write(self, data):
        if self._transport_protocol == protocol.TRANSPORT_TCP:
            self._transport.write(data)
        elif self._transport_protocol == protocol.TRANSPORT_UDP:
            self._transport.sendto(data, self._peername)
        else:
            raise NotImplementedError

    def close(self):
        if self._transport_protocol == protocol.TRANSPORT_TCP:
            if self._transport is not None:
                self._transport.close()
        elif self._transport_protocol == protocol.TRANSPORT_UDP:
            pass
        else:
            raise NotImplementedError

    def handle_tcp_connection_made(self, transport):
        self.keep_alive_open()
        self._stage = self.STAGE_INIT
        self._transport = transport
        self._transport_protocol = protocol.TRANSPORT_TCP
        self._cryptor = cryptor.Cryptor(protocol.TRANSPORT_TCP, self._key)
        self._peername = self._transport.get_extra_info('peername')
        self._logger = logging.getLogger('<LocalTCP{0} {1}>'.format(self._peername, hex(id(self))))
        self._logger.debug('tcp connection made')

    def handle_udp_connection_made(self, transport, peername):
        self._stage = self.STAGE_INIT
        self._transport = transport
        self._transport_protocol = protocol.TRANSPORT_UDP
        self._cryptor = cryptor.Cryptor(protocol.TRANSPORT_UDP, self._key)
        self._peername = peername
        self._logger = logging.getLogger('<LocalUDP{0} {1}>'.format(self._peername, hex(id(self))))
        self._logger.debug('udp connection made')

    def handle_data_received(self, data):
        self._logger.debug('received len={}'.format(len(data)))
        data = self._cryptor.decrypt(data)
        if self._stage == self.STAGE_INIT:
            coro = self._handle_stage_init(data)
            asyncio.ensure_future(coro)
        elif self._stage == self.STAGE_CONNECT:
            coro = self._handle_stage_connect(data)
            asyncio.ensure_future(coro)
        elif self._stage == self.STAGE_STREAM:
            self._handle_stage_stream(data)
        elif self._stage == self.STAGE_ERROR:
            self._handle_stage_error()
        else:
            self._logger.warning('unknown stage={}'.format(self._stage))

    def handle_eof_received(self):
        self._logger.debug('eof received')

    def handle_connection_lost(self, exc):
        self._logger.debug('lost exc={exc}'.format(exc=exc))
        if self._remote is not None:
            self._remote.close()

    def _handle_exception(self):
        pass

    async def _handle_stage_init(self, data):
        atype, dst_addr, dst_port, payload = data[0], None, None, None
        if atype == protocol.ATYPE_IPV4:
            dst_addr, (dst_port,), payload = socket.inet_ntop(socket.AF_INET, data[1:5]), \
                                             struct.unpack('!H', data[5:7]), \
                                             data[7:]
        elif atype == protocol.ATYPE_DOMAINNAME:
            len_domain = data[1]
            dst_addr, (dst_port,), payload = data[2:2 + len_domain], \
                                             struct.unpack('!H', data[2 + len_domain:2 + len_domain + 2]), \
                                             data[2 + len_domain + 2:]
        elif atype == protocol.ATYPE_IPV6:
            dst_addr, (dst_port,), payload = socket.inet_ntop(socket.AF_INET6, data[1:17]), \
                                             struct.unpack('!H', data[17:19]), \
                                             data[19:]
        else:
            self._logger.warning('unknown atype={}'.format(atype))
            self.close()
            return

        self._logger.debug('connecting {}:{}'.format(dst_addr, dst_port))

        loop = asyncio.get_event_loop()
        if self._transport_protocol == protocol.TRANSPORT_TCP:
            self._stage = self.STAGE_CONNECT
            coro = loop.create_connection(lambda: RemoteTCP(dst_addr, dst_port, payload, self._key, self),
                                          dst_addr, dst_port)
            try:
                remote_transport, remote_instance = await coro
            except (IOError, OSError) as e:
                self._logger.debug('connection failed, {} e={}'.format(type(e), e))
                self.close()
                self._stage = self.STAGE_DESTROY
            except Exception as e:
                self._logger.warning('connection failed, {} e={}'.format(type(e), e))
                self.close()
                self._stage = self.STAGE_ERROR
            else:
                self._logger.debug('connection established, remote={}'.format(remote_instance))
                self._remote = remote_instance
                self._stage = self.STAGE_STREAM
        elif self._transport_protocol == protocol.TRANSPORT_UDP:
            self._stage = self.STAGE_INIT
            coro = loop.create_datagram_endpoint(lambda: RemoteUDP(dst_addr, dst_port, payload, self._key, self),
                                                 remote_addr=(dst_addr, dst_port))
            asyncio.ensure_future(coro)
        else:
            raise NotImplementedError

    async def _handle_stage_connect(self, data):
        # after stage_init, it takes few time to connect to remote, but sometimes the impatient ss-client
        # send next payload immediately, so we have to handle it.
        self._logger.debug('wait until connection established')
        for i in range(30):
            if self._stage == self.STAGE_CONNECT:  # continue waiting
                await asyncio.sleep(0.2)
            elif self._stage == self.STAGE_STREAM:  # remote_transport is not None
                self._logger.debug('connection established')
                self._remote.write(data)
                return
            else:  # some error arise
                self._logger.debug('some error happened, stage={}'.format(self._stage))
                return
        # resolve time out, do something
        self._logger.warning('time out, stage={}'.format(self._stage))
        self.close()

    def _handle_stage_stream(self, data):
        self._logger.debug('relay data')
        self.keep_alive_active()
        self._remote.write(data)

    def _handle_stage_error(self):
        self.close()


class LocalTCP(asyncio.Protocol):
    # this class will construct as long as a new connection is ready, and
    # connection_made will be called after the connection is established
    def __init__(self, key):
        self._handler = LocalHandler(key)

    def connection_made(self, transport):
        self._handler.handle_tcp_connection_made(transport)

    def data_received(self, data):
        self._handler.handle_data_received(data)

    def eof_received(self):
        self._handler.handle_eof_received()

    def connection_lost(self, exc):
        self._handler.handle_connection_lost(exc)


class LocalUDP(asyncio.DatagramProtocol):
    # this class will construct only once, and
    # connection_made() will be called immediately after socket.bind()
    def __init__(self, key):
        self._key = key
        self._transport = None
        self._instances = {}

    def connection_made(self, transport):
        self._transport = transport

    def datagram_received(self, data, peername):
        if peername in self._instances:
            handler = self._instances[peername]
        else:
            handler = LocalHandler(self._key)
            self._instances[peername] = handler
            handler.handle_udp_connection_made(self._transport, peername)
        handler.handle_data_received(data)

    def error_received(self, exc):
        pass


def run_server():
    loop = asyncio.get_event_loop()

    tcp_servers = []
    udp_transports = []
    for port, key in shell.config['port_key']:
        logging.info('Serving on {}:{}'.format(shell.config['local_address'], port))
        tcp_server = loop.run_until_complete(loop.create_server(lambda: LocalTCP(key), shell.config['local_address'], port))
        tcp_servers.append(tcp_server)
        udp_transport, _ = loop.run_until_complete(
            loop.create_datagram_endpoint(lambda: LocalUDP(key), local_addr=(shell.config['local_address'], port)))
        udp_transports.append(udp_transport)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    for udp_transport in udp_transports:
        udp_transport.close()
    for tcp_server in tcp_servers:
        tcp_server.close()
        loop.run_until_complete(tcp_server.wait_closed())

    loop.close()


if __name__ == '__main__':
    shell.init_config()
    shell.init_logging()
    run_server()
