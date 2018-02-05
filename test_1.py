import logging
import asyncio


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    a = asyncio.Transport()
    # coro = loop.create_server(A, '127.0.0.1', 1521)
    server = loop.run_until_complete(coro)

    logging.info('Serving on {}'.format(server.sockets[0].getsockname()))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    server.close()
    loop.run_until_complete(server.wait_closed())
    loop.close()