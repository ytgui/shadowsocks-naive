import os
import time
import struct


def main():
    buffer = os.urandom(1024 * 1024)
    buffer_origin = buffer[:]
    before = time.time()
    #
    nonce = 0x37
    buffer = bytearray(buffer)
    for i, x in enumerate(buffer):
        buffer[i] = x ^ nonce
        nonce = buffer[i]
    buffer = bytes(buffer)
    #
    nonce = 0x37
    buffer = bytearray(buffer)
    for i, x in enumerate(buffer):
        buffer[i] = x ^ nonce
        nonce = x
    buffer = bytes(buffer)
    #
    after = time.time()
    assert buffer == buffer_origin
    print(after - before)


def main_2():
    buffer = os.urandom(1024 * 1024)
    buffer_origin = buffer[:]
    before = time.time()
    #
    nonce = 0x12345678
    buffer = bytearray(buffer)
    for i in range(0, len(buffer), 4):
        x = int.from_bytes(buffer[i:i + 4], byteorder='big')
        nonce = x ^ nonce
        buffer[i:i + 4] = nonce.to_bytes(4, byteorder='big')
    buffer = bytes(buffer)
    #
    nonce = 0x12345678
    buffer = bytearray(buffer)
    for i in range(0, len(buffer), 4):
        x = int.from_bytes(buffer[i:i + 4], byteorder='big')
        buffer[i:i + 4] = (x ^ nonce).to_bytes(4, byteorder='big')
        nonce = x
    buffer = bytes(buffer)
    #
    after = time.time()
    assert buffer == buffer_origin
    print(after - before)


if __name__ == "__main__":
    main()
    main_2()
