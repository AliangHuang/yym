import json
import os
import struct
import subprocess
import sys

import pytest

from yym.hashing import unicode_hash
from yym.memory import GameSession, MemoryReader, PythonObjects, UnsupportedClient


def test_unicode_hash_matches_cpython_siphash13():
    values = ['', 'a', 'Globals', 'pet_yuhun', 'café', '日常', 'cat🐱', 'x' * 81]
    script = 'import json; print(json.dumps([hash(v) for v in ' + repr(values) + ']))'
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True,
                            env={**os.environ, 'PYTHONHASHSEED': '0'}, check=True)
    assert [unicode_hash(v, bytes(16)) for v in values] == json.loads(result.stdout)


class BytesReader:
    def __init__(self):
        self.raw = bytearray(4096)
    def read(self, address, length):
        return bytes(self.raw[address:address + length])
    def u64(self, address):
        return struct.unpack('<Q', self.read(address, 8))[0]
    def put(self, address, value):
        struct.pack_into('<Q', self.raw, address, value)


def test_dictionary_collision_tombstone_and_split_values():
    reader = BytesReader()
    py = object.__new__(PythonObjects)
    py.r, py.hash_secret, py.hash_verified = reader, bytes(16), True
    py.atom = lambda pointer: {1000: 0, 1008: 8}[pointer]
    # A size-8 integer-key dictionary: 0 and 8 share the same initial hash slot.
    address, keys, values = 64, 128, 512
    reader.put(address + 32, keys)
    reader.put(address + 40, values)
    reader.raw[keys + 8:keys + 11] = bytes([3, 3, 0])
    reader.raw[keys + 32:keys + 40] = b'\xff' * 8
    reader.raw[keys + 32] = 0
    reader.raw[keys + 33] = 1
    reader.put(keys + 40 + 8, 1000)
    reader.put(keys + 40 + 24 + 8, 1008)
    reader.put(values, 2000)
    reader.put(values + 8, 2008)
    assert py.lookup(address, 8) == 2008
    reader.raw[keys + 32] = 254  # Deleted slot; lookup must keep probing.
    assert py.lookup(address, 8) == 2008
    with pytest.raises(KeyError):
        py.lookup(address, 16)


def test_readable_mapping_boundaries_and_relocation():
    reader = object.__new__(MemoryReader)
    reader.update_maps('1000-2000 r--p 0 00:00 0\n3000-4000 rw-p 0 00:00 0')
    assert reader.region(0x1FFF) == (0x1000, 0x2000)
    with pytest.raises(ValueError):
        reader.region(0x1FFF, 2)
    with pytest.raises(ValueError):
        reader.region(0x2000)
    reader.update_maps('5000-6000 rw-p 0 00:00 0')
    with pytest.raises(ValueError):
        reader.region(0x1000)


def test_unknown_client_version_is_rejected_before_memory_connection():
    class Adb:
        def shell(self, command, **kwargs):
            return '0' * 64 + ' libclient.so'
    with pytest.raises(UnsupportedClient, match='尚未适配'):
        GameSession(Adb(), 100, '1000-9000 r--p 00000000 00:00 0 /app/libclient.so')
