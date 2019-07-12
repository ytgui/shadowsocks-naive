import time
import asyncio
import logging


class TimeoutHandler:
    def __init__(self, timeout):
        self._last_active_time = time.time()
        self._timeout_seconds = 60.0 if timeout is None else timeout

    def is_alive(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def keep_alive_enable(self):
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


class BaseProtocol(asyncio.Protocol, TimeoutHandler):
    def __init__(self, callbacks, statistic=False, timeout=None):
        TimeoutHandler.__init__(self, timeout)
        self._transport = None
        self._peername = None
        self._callbacks = callbacks
        #
        self._total_send = 0
        self._total_recv = 0
        if statistic is True:
            asyncio.ensure_future(self._watchdog())
    
    async def _watchdog(self):
        def format_size(size):
            if size < 1024:
                size, suffix = size, 'B'
            elif size < 1024 * 1024:
                size, suffix = size / 1024, 'K'
            elif size < 1024 * 1024 * 1024:
                size, suffix = size / (1024 * 1024), 'M'
            else:
                size, suffix = size / (1024 * 1024 * 1024), 'G'
            return '{:.02f} {}'.format(size, suffix)

        while True:
            await asyncio.sleep(20.0)
            logging.info('[TOTAL] recv: {} send {}'
                         .format(format_size(self._total_recv),
                                 format_size(self._total_send)))

    def write(self, data):
        # Write some data bytes to the transport.
        # This method does not block; it buffers the data and
        # arranges for it to be sent out asynchronously.
        self._transport.write(data)
        self._total_send += len(data)
    
    # ----------------------------------------------
    # ---------- TimeoutHandler overridden ---------
    # ----------------------------------------------
    def is_alive(self):
        if self._transport is None:
            return False
        elif self._transport.is_closing():
            return False
        else:
            return True

    def close(self):
        # once we `call transport.close()`, a flag in transport
        # set from `closing` to  `closed`
        if self.is_alive():
            self._transport.close()
    
    # ----------------------------------------------
    # ------- asyncio.Protocol overridden ----------
    # ----------------------------------------------
    def connection_made(self, transport):
        self.keep_alive_enable()
        self._transport = transport
        self._peername = transport.get_extra_info('peername')
        self._callbacks[0]()

    def data_received(self, data):
        assert isinstance(data, bytes)
        self.keep_alive_active()
        self._callbacks[1](data)
        self._total_recv += len(data)

    def connection_lost(self, exc):
        self._callbacks[2](exc)
