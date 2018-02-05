import time
import asyncio


class TimeoutHandler:
    def __init__(self):
        self._last_active_time = time.time()
        self._timeout_seconds = 200.0

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


class LocalProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        self.local_connection_made(transport)

    def data_received(self, data):
        self.local_data_received(data)

    def connection_lost(self, exc):
        self.local_connection_lost(exc)

    def local_connection_made(self, transport):
        raise NotImplementedError

    def local_data_received(self, data):
        raise NotImplementedError

    def local_connection_lost(self, exc):
        raise NotImplementedError

    def client_data_received(self, data):
        raise NotImplementedError


class ClientProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        self.server_connection_made(transport)

    def data_received(self, data):
        self.server_data_received(data)

    def connection_lost(self, exc):
        self.server_connection_lost(exc)

    def server_connection_made(self, transport):
        raise NotImplementedError

    def server_data_received(self, data):
        raise NotImplementedError

    def server_connection_lost(self, exc):
        raise NotImplementedError

    def local_data_received(self, instance_id, data):
        raise NotImplementedError


class ServerProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        self.client_connection_made(transport)

    def data_received(self, data):
        self.client_data_received(data)

    def connection_lost(self, exc):
        self.client_connection_lost(exc)

    def client_connection_made(self, transport):
        raise NotImplementedError

    def client_data_received(self, data):
        raise NotImplementedError

    def client_connection_lost(self, exc):
        raise NotImplementedError

    def remote_data_received(self, handler_id, data):
        raise NotImplementedError


class RemoteProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        self.remote_connection_made(transport)

    def data_received(self, data):
        self.remote_data_received(data)

    def connection_lost(self, exc):
        self.remote_connection_lost(exc)

    def remote_connection_made(self, transport):
        raise NotImplementedError

    def remote_data_received(self, data):
        raise NotImplementedError

    def remote_connection_lost(self, exc):
        raise NotImplementedError

    def server_data_received(self, data):
        raise NotImplementedError
