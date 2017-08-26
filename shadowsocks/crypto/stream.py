import os
import struct
import hashlib
import logging
import cryptography.exceptions
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import (Cipher, algorithms, modes)

from shadowsocks import protocol
from shadowsocks.crypto import hkdf


class StreamCrypto:
    def __init__(self, transport_protocol, key):
        self._transport_protocol = transport_protocol
        self._key = key
        self._iv = None
        self._iv_len = 16
        self._first_package = True
        self._encryptor = None
        self._decryptor = None

    def __del__(self):
        if self._encryptor is not None:
            self._encryptor.finalize() # destruct context of openssl
        if self._decryptor is not None:
            self._decryptor.finalize()

    def encrypt(self, data):
        if self._first_package is True or self._transport_protocol == protocol.TRANSPORT_UDP:
            self._first_package = False
            self._iv = os.urandom(self._iv_len)
            self._encryptor = Cipher(
                algorithms.AES(self._key),
                modes.CFB(self._iv),
                backend=default_backend()
            ).encryptor()
            return self._iv + self._encrypt_impl(data, self._key, self._iv)
        else:
            return self._encrypt_impl(data, self._key, self._iv)

    def decrypt(self, data):
        if self._first_package is True or self._transport_protocol == protocol.TRANSPORT_UDP:
            self._first_package = False
            self._iv, data = data[:self._iv_len], data[self._iv_len:]
            self._decryptor = Cipher(
                algorithms.AES(self._key),
                modes.CFB(self._iv),
                backend=default_backend()
            ).decryptor()
        return self._decrypt_impl(data, self._key, self._iv)

    def _encrypt_impl(self, plaintext, key, iv):
        return self._encryptor.update(plaintext)

    def _decrypt_impl(self, ciphertext, key, iv):
        return self._decryptor.update(ciphertext)
