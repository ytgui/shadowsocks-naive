import json
import logging
from shadowsocks import cryptor

supported_methods = {'aes-128-cfb': (16, 16, 'Stream'),
             'aes-192-cfb': (24, 16, 'Stream'),
             'aes-256-cfb': (32, 16, 'Stream')}
config = {}
config_default = {}


def init_config():
    global config
    config = json.load(open('shadowsocks.json'))

    if config.get('local_address', None) is None:
        raise ValueError('local_address must be assigned')

    if config.get('method', None) is None:
        raise ValueError('method must be assigned')
    if config['method'] not in supported_methods:
        raise ValueError('method not support')
    method = config['method']
    (key_len, iv_len, cipher) = supported_methods[method]
    config['cipher'] = cipher

    if config.get('port_password', None) is None:
        raise ValueError('port_password must be assigned')
    else:
        m = []
        port_password = config['port_password']
        for port in port_password:
            password = port_password[port].encode()
            key = cryptor.EVP_BytesToKey(password, key_len)
            m.append((port, key))
        config['port_key'] = m


def init_logging():
    handler = None
    logging.basicConfig(handlers=handler,
                        format='[%(levelname)s] %(asctime)s - %(process)d - %(name)s - %(funcName)s() - %(message)s',
                        level=logging.INFO)
