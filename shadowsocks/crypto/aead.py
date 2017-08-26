import os
import struct
from shadowsocks import protocol
from shadowsocks.crypto import hkdf
import cryptography.exceptions
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import (Cipher, algorithms, modes)


def nonce_increase(nonce, nlen):
    ns = struct.unpack('<{0}B'.format(nlen), nonce)
    ns = list(ns)
    c = 1
    for idx, n in enumerate(ns):
        c += n
        ns[idx] = c & 0xFF
        c >>= 8
    return struct.pack('<{0}B'.format(nlen), *ns)


class AeadCrypto:
    AEAD_CHUNK_SIZE_MASK = 0x3FFF
    AEAD_CHUNK_SIZE_MAX = AEAD_CHUNK_SIZE_MASK

    def __init__(self, password, method):
        self._password = password
        self._first_package = True
        self._iv, self._iv_len = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00', 12
        if method == 'encrypt':
            self._salt = os.urandom(32)
            self._key = hkdf.Hkdf(self._salt, self._password).expand(b'ss-subkey')
        elif method == 'decrypt':
            self._salt = None
            self._key = None

    def encrypt(self, plaintext):
        ciphertext, tag = self._encrypt_impl(plaintext, self._key, self._iv)
        self._iv = nonce_increase(self._iv, self._iv_len)
        return ciphertext + tag

    def decrypt(self, ciphertext, tag):
        if self._first_package:
            self._first_package = False
            self._salt, ciphertext = ciphertext[:4], ciphertext[4:]
            self._key = hkdf.Hkdf(self._salt, self._password).expand(b'ss-subkey')
        c1, t1, c2, t2 = ciphertext[:2], ciphertext[2:6], ciphertext[6:-4], ciphertext[-4:]
        length = self._decrypt_impl(c1, t1)
        self._iv = nonce_increase(self._iv, self._iv_len)
        payload = self._decrypt_impl(c2, t2)
        self._iv = nonce_increase(self._iv, self._iv_len)

    def _encrypt_impl(self, plaintext, key, iv):
        encryptor = Cipher(
            algorithms.AES(self._key),
            modes.GCM(self._iv),
            backend=default_backend()
        ).encryptor()
        ciphertext = encryptor.update(plaintext) + encryptor.finalize()
        return ciphertext, encryptor.tag

    def _decrypt_impl(self, ciphertext, tag):
        decryptor = Cipher(
            algorithms.AES(self._key),
            modes.GCM(self._iv, tag),
            backend=default_backend()
        ).decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        return plaintext

    def _check_key(self):
        pass

    def _check_iv(self):
        pass

    def _check_tag(self):
        pass
