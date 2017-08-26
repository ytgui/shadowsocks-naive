from distutils.core import setup


setup(
    name='shadowsocks-naive',
    version='0.1.0',
    license='GNU General Public License version 3',
    description='',
    author='bosskwei',
    author_email='bosskwei@gmail.com',
    url='',
    packages=['shadowsocks', 'shadowsocks.crypto'],
    install_requires=['cryptography'],
    classifiers=[
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: Implementation :: CPython',
        'Topic :: Internet :: Proxy Servers',
    ]
)
