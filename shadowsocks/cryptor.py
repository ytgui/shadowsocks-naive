import os
import struct
import logging
import hashlib
from shadowsocks import shell, protocol
from shadowsocks.crypto import stream, aead


def EVP_BytesToKey(password, key_len):
    m = []
    for i in range(key_len // 16):
        if i > 0:
            data = m[i - 1] + password
        else:
            data = password
        md5 = hashlib.md5()
        md5.update(data)
        m.append(md5.digest())
    return b''.join(m)


class Cryptor:
    def __init__(self, transport_protocol, key):
        if shell.config['cipher'] == 'Stream':
            self._crypto = stream.StreamCrypto(transport_protocol, key)
        else:
            raise NotImplementedError

    def encrypt(self, data):
        return self._crypto.encrypt(data)

    def decrypt(self, data):
        return self._crypto.decrypt(data)


if __name__ == '__main__':
    pass
