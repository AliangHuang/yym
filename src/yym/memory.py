"""Read-only CPython object reader for explicitly supported client libraries.

No code is evaluated in Android. All addresses are rediscovered per process.
"""
from __future__ import annotations

import hashlib
from bisect import bisect_right
from datetime import datetime, date
from collections.abc import Mapping
from importlib.resources import files
import json
import re
import shlex
import socket
import struct
import time

from yym.mumu import Adb
from yym.hashing import unicode_hash


class UnsupportedClient(RuntimeError):
    pass


class MemoryReader:
    def __init__(self, adb: Adb, pid: int, maps: str, cancel=None):
        self.cancel = cancel
        self.update_maps(maps)
        self.cache: dict[int, bytes] = {}
        self.requests = 0
        self.sock = socket.create_connection(('127.0.0.1', 5037), timeout=4)
        self.sock.settimeout(4)
        try:
            service = (f"exec:sh -c 'while read a n; do dd if=/proc/{int(pid)}/mem "
                       "bs=4096 skip=$a count=$n iflag=skip_bytes,count_bytes status=none 2>/dev/null; done'")
            for command in (f'host:transport:{adb.serial}', service):
                raw = command.encode()
                self.sock.sendall(f'{len(raw):04x}'.encode() + raw)
                if self.recv(4) != b'OKAY':
                    raise ConnectionError('ADB memory service unavailable')
        except BaseException:
            self.sock.close()
            raise

    def update_maps(self, maps: str) -> None:
        self.regions = sorted((int(p[0].split('-')[0], 16), int(p[0].split('-')[1], 16))
                              for line in maps.splitlines() if (p := line.split())[1].startswith('r'))
        self.region_starts = [a for a, _ in self.regions]

    def region(self, address: int, size: int = 1) -> tuple[int, int]:
        index = bisect_right(self.region_starts, address) - 1
        if index < 0 or address + size > self.regions[index][1]:
            raise ValueError('Invalid memory range')
        return self.regions[index]

    def recv(self, size: int) -> bytes:
        chunks, remaining = [], size
        while remaining:
            part = self.sock.recv(remaining)
            if not part:
                raise ConnectionError('ADB connection closed')
            chunks.append(part)
            remaining -= len(part)
        return b''.join(chunks)

    def read(self, address: int, size: int) -> bytes:
        if size == 0:
            return b''
        if size < 0 or size > 4 * 1024 * 1024:
            raise ValueError('Invalid memory range')
        self.region(address, size)
        chunks = []
        while size:
            if self.cancel and self.cancel.is_set():
                raise ConnectionAbortedError('Reader stopping')
            page, offset = address & ~4095, address & 4095
            length = min(size, 4096 - offset)
            if page not in self.cache:
                # Batch contiguous pages in the same readable mapping. Spawning dd once per
                # individual object makes cold module discovery unnecessarily expensive.
                region = self.region(page)
                start = max(region[0], page & ~65535)
                end = min(region[1], (page & ~65535) + 65536)
                self.sock.sendall(f'{start} {end - start}\n'.encode())
                raw = self.recv(end - start)
                for at in range(start, end, 4096):
                    self.cache[at] = raw[at - start:at - start + 4096]
                self.requests += 1
            chunks.append(self.cache[page][offset:offset + length])
            address += length
            size -= length
        return b''.join(chunks)

    def u64(self, address: int) -> int:
        return struct.unpack('<Q', self.read(address, 8))[0]

    def i64(self, address: int) -> int:
        return struct.unpack('<q', self.read(address, 8))[0]

    def close(self) -> None:
        self.sock.close()


class PythonObjects:
    def __init__(self, reader: MemoryReader, base: int, symbols: dict):
        self.r = reader
        self.types = {base + value: name.removeprefix('Py').removesuffix('_Type')
                      for name, value in symbols.items() if name.endswith('_Type')}
        self.type_names: dict[int, str] = {}
        self.hash_secret = reader.read(base + symbols['_Py_HashSecret'], 16) if '_Py_HashSecret' in symbols else None
        self.hash_verified = False

    def kind(self, address: int) -> str:
        if not address:
            return 'NoneType'
        typ = self.r.u64(address + 8)
        if typ in self.types:
            return self.types[typ]
        if typ not in self.type_names:
            ptr = self.r.u64(typ + 24)
            self.type_names[typ] = self.r.read(ptr, 100).split(b'\0')[0].decode('utf-8', 'replace')
        name = self.type_names[typ]
        # CPython's subclass flags permit ADict/AList without executing their methods.
        flags = self.r.u64(typ + 168)
        for bit, family in [(29, 'Dict'), (25, 'List'), (26, 'Tuple'), (28, 'Unicode'), (24, 'Long')]:
            if flags & (1 << bit):
                return family
        return name

    def text(self, address: int) -> str:
        header = self.r.read(address, 80)
        size = struct.unpack_from('<q', header, 16)[0]
        state = struct.unpack_from('<I', header, 32)[0]
        kind, compact, ascii_only = (state >> 2) & 7, (state >> 5) & 1, (state >> 6) & 1
        if not 0 <= size <= 1_000_000 or kind not in (1, 2, 4):
            raise ValueError('Invalid string object')
        data = address + (48 if ascii_only else 72) if compact else struct.unpack_from('<Q', header, 72)[0]
        return self.r.read(data, size * kind).decode({1: 'latin1', 2: 'utf-16-le', 4: 'utf-32-le'}[kind], 'replace')

    def atom(self, address: int):
        kind = self.kind(address)
        if kind == 'NoneType':
            return None
        if kind == 'Unicode':
            return self.text(address)
        if kind in ('Long', 'Bool'):
            n = self.r.i64(address + 16)
            if abs(n) > 10:
                raise ValueError('Invalid integer object')
            words = struct.unpack('<' + 'I' * abs(n), self.r.read(address + 24, abs(n) * 4))
            value = sum(v << (30 * i) for i, v in enumerate(words)) * (-1 if n < 0 else 1)
            return bool(value) if kind == 'Bool' else value
        if kind == 'Float':
            return struct.unpack('<d', self.r.read(address + 16, 8))[0]
        if kind == 'Bytes':
            size = self.r.i64(address + 16)
            if not 0 <= size <= 1_000_000:
                raise ValueError('Invalid byte string')
            return self.r.read(address + 32, size).hex()
        if kind == 'ObjectId':
            return self.atom(self.r.u64(address + 16))
        if kind in ('datetime.datetime', 'datetime.date'):
            raw = self.r.read(address + 25, 10 if kind == 'datetime.datetime' else 4)
            year = raw[0] * 256 + raw[1]
            if kind == 'datetime.date':
                return date(year, raw[2], raw[3]).isoformat()
            return datetime(year, raw[2], raw[3], raw[4], raw[5], raw[6]).isoformat()
        return {'type': kind}

    def entries(self, address: int, tail: int | None = None) -> list[tuple[object, int]]:
        if self.kind(address) != 'Dict':
            raise ValueError('Expected dictionary')
        used = self.r.i64(address + 16)
        keys, values = self.r.u64(address + 32), self.r.u64(address + 40)
        header = self.r.read(keys, 32)
        logbytes, kind = header[9], header[10]
        count = struct.unpack_from('<q', header, 24)[0]
        if not 0 <= used <= 100_000 or not 0 <= count <= 100_000 or logbytes > 24:
            raise ValueError('Dictionary changed or layout invalid')
        width = 24 if kind == 0 else 16
        start = keys + 32 + (1 << logbytes)
        first = max(0, count - tail) if tail else 0
        raw = self.r.read(start + first * width, (count - first) * width)
        vals = self.r.read(values + first * 8, (count - first) * 8) if values else None
        result = []
        for index in range(count - first):
            key, value = struct.unpack_from('<QQ', raw, index * width + (8 if kind == 0 else 0))
            if vals:
                value = struct.unpack_from('<Q', vals, index * 8)[0]
            if key and value:
                decoded_key = self.atom(key)
                if isinstance(decoded_key, (str, int, float, bool)):
                    result.append((decoded_key, value))
        if self.r.i64(address + 16) != used:
            raise ValueError('Dictionary changed during reading')
        return result

    def mapping(self, address: int) -> dict:
        return dict(self.entries(address))

    def lookup(self, address: int, key: str | int) -> int:
        if not self.hash_secret or not self.hash_verified:
            values = self.mapping(address)
            return values[key]
        keys, values = self.r.u64(address + 32), self.r.u64(address + 40)
        header = self.r.read(keys, 32)
        logsize, logbytes, kind = header[8], header[9], header[10]
        if logsize > 24 or logbytes > 28:
            raise ValueError('Invalid dictionary index size')
        width = 1 << (logbytes - logsize)
        if width not in (1, 2, 4, 8):
            raise ValueError('Invalid dictionary index width')
        mask = (1 << logsize) - 1
        if isinstance(key, str):
            hashed = unicode_hash(key, self.hash_secret)
        else:
            hashed = abs(key) % ((1 << 61) - 1) * (-1 if key < 0 else 1)
            if hashed == -1:
                hashed = -2
        perturb = hashed & ((1 << 64) - 1)
        index = perturb & mask
        entries = keys + 32 + (1 << logbytes)
        entry_width = 24 if kind == 0 else 16
        for _ in range(mask + 2):
            slot = int.from_bytes(self.r.read(keys + 32 + index * width, width), 'little', signed=True)
            if slot == -1:
                raise KeyError(key)
            if slot >= 0:
                offset = entries + slot * entry_width + (8 if kind == 0 else 0)
                candidate, value = struct.unpack('<QQ', self.r.read(offset, 16))
                if candidate and self.atom(candidate) == key:
                    value = self.r.u64(values + slot * 8) if values else value
                    if value:
                        return value
                    raise KeyError(key)
            perturb >>= 5
            index = (index * 5 + perturb + 1) & mask
        raise ValueError('Dictionary lookup did not converge')

    def lazy_mapping(self, address: int):
        if self.kind(address) != 'Dict':
            raise ValueError('Expected dictionary')
        return LiveDict(self, address)

    def lazy_attrs(self, address: int):
        typ = self.r.u64(address + 8)
        if self.r.u64(typ + 168) & 16:
            dictionary = self.r.u64(address - 24)
            if dictionary:
                return self.lazy_mapping(dictionary)
        return self.attrs(address)

    def tagged_value(self, address: int, field: str):
        pointer, count = self.r.u64(address + 16), self.r.u64(address + 24)
        if count > 10_000:
            raise ValueError('Invalid tagged dictionary')
        for key, value in struct.iter_unpack('<QQ', self.r.read(pointer, count * 16)):
            if self.atom(key & ~7) == field:
                return self.decode(value & ~7)
        raise KeyError(field)

    def sequence(self, address: int) -> tuple[int, ...]:
        kind = self.kind(address)
        if kind not in ('List', 'Tuple'):
            raise ValueError('Expected sequence')
        size = self.r.i64(address + 16)
        if not 0 <= size <= 100_000:
            raise ValueError('Invalid sequence')
        start = self.r.u64(address + 24) if kind == 'List' else address + 24
        return struct.unpack('<' + 'Q' * size, self.r.read(start, size * 8))

    def attrs(self, address: int) -> dict[str, int]:
        typ = self.r.u64(address + 8)
        flags, offset = self.r.u64(typ + 168), self.r.i64(typ + 288)
        if flags & 16:
            dictionary = self.r.u64(address - 24)
            if dictionary:
                return self.mapping(dictionary)
            values = self.r.u64(address - 32)
            if not values:
                return {}
            keys = self.r.u64(typ + 880)
            header = self.r.read(keys, 32)
            count = struct.unpack_from('<q', header, 24)[0]
            if not 0 <= count <= 2048:
                raise ValueError('Invalid object attribute layout')
            raw = self.r.read(keys + 32 + (1 << header[9]), count * 16)
            result = {}
            for index in range(count):
                key = struct.unpack_from('<Q', raw, index * 16)[0]
                value = self.r.u64(values + index * 8)
                if key and value:
                    result[self.text(key)] = value
            return result
        if offset > 0:
            pointer = self.r.u64(address + offset)
            return self.mapping(pointer) if pointer else {}
        return {}

    def decode(self, address: int, depth: int = 0, max_depth: int = 5, limit: int = 80):
        address &= ~7
        kind = self.kind(address)
        if depth >= max_depth:
            return self.atom(address)
        if kind == 'taggeddict.taggeddict':
            pointer, count = self.r.u64(address + 16), self.r.u64(address + 24)
            if count > 100_000:
                raise ValueError('Invalid tagged dictionary')
            raw = self.r.read(pointer, count * 16)
            items = [(self.atom(k & ~7), v & ~7) for k, v in struct.iter_unpack('<QQ', raw)]
        elif kind == 'Dict':
            items = self.entries(address)
        elif kind in ('List', 'Tuple'):
            return [self.decode(a, depth + 1, max_depth, limit) for a in self.sequence(address)[:limit]]
        else:
            return self.atom(address)
        return {str(k): self.decode(v, depth + 1, max_depth, limit)
                for k, v in items[:limit] if isinstance(k, (str, int, float, bool))}


class GameSession:
    def __init__(self, adb: Adb, pid: int, maps: str, cancel=None):
        self.adb, self.pid = adb, pid
        lines = [line.split() for line in maps.splitlines() if '/libclient.so' in line]
        if not lines:
            raise UnsupportedClient('游戏客户端库尚未加载')
        library = lines[0][-1]
        self.base = int(lines[0][0].split('-')[0], 16) - int(lines[0][2], 16)
        signature = adb.shell('sha256sum ' + shlex.quote(library), timeout=20).split()[0]
        profile_file = files('yym').joinpath('profiles', f'{signature}.json')
        if not profile_file.is_file():
            raise UnsupportedClient(f'客户端版本尚未适配（{signature[:12]}）')
        profile = json.loads(profile_file.read_text(encoding='utf-8'))
        if profile.get('python_abi') != '3.11' or profile.get('architecture') != 'x86_64' or profile.get('sha256') != signature:
            raise UnsupportedClient('客户端适配尚未通过校验')
        self.signature = signature
        self.reader = MemoryReader(adb, pid, maps, cancel)
        self.py = PythonObjects(self.reader, self.base, profile['symbols'])
        self.modules: dict[str, int] = {}
        self.config_cache: dict[tuple[str, int], tuple[float, object]] = {}
        try:
            fn = self.base + profile['symbols']['PyInterpreterState_Head']
            instruction = self.reader.read(fn, 12)
            if instruction[:3] != b'\x48\x8b\x05':
                raise UnsupportedClient('解释器入口校验失败')
            got = fn + 7 + struct.unpack_from('<i', instruction, 3)[0]
            self.runtime = self.reader.u64(got)
            self.refresh_modules(full=True)
            self.prepare()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def find(adb: Adb) -> tuple[int, str]:
        package = 'com.netease.onmyoji.wyzymnqsd_cps'
        candidates = [package]
        try:
            candidates += [line.removeprefix('package:') for line in adb.shell('pm list packages com.netease.onmyoji').splitlines()]
        except RuntimeError:
            pass
        for name in dict.fromkeys(candidates):
            if not re.fullmatch(r'com\.netease\.onmyoji[\w.]*', name):
                continue
            try:
                pids = adb.shell(f'pidof {name}').split()
                if pids:
                    pid = int(pids[0])
                    return pid, adb.shell(f'cat /proc/{pid}/maps')
            except (RuntimeError, ValueError):
                continue
        raise RuntimeError('等待阴阳师启动并登录')

    def refresh_modules(self, full: bool = False) -> None:
        interpreter = self.reader.u64(self.runtime + 0x28)
        modules = self.reader.u64(interpreter + 0x378)
        if self.py.kind(modules) != 'Dict':
            raise UnsupportedClient('解释器模块布局校验失败')
        self.module_pointer = modules
        if full and self.py.hash_secret:
            # Validate the host hash algorithm against an actual key before using it.
            keys = self.reader.u64(modules + 32)
            h = self.reader.read(keys, 32)
            entry = keys + 32 + (1 << h[9]) + (8 if h[10] == 0 else 0)
            pointer = self.reader.u64(entry)
            if pointer and self.py.kind(pointer) == 'Unicode':
                text = self.py.text(pointer)
                self.py.hash_verified = unicode_hash(text, self.py.hash_secret) == self.reader.i64(pointer + 24)
        version = self.reader.u64(modules + 24)
        if not self.py.hash_verified and (full or version != getattr(self, '_module_version', None)):
            self.modules.update({str(k): v for k, v in self.py.entries(modules, tail=None if full else 384)})
        self._module_version = version

    def module(self, name: str) -> dict:
        pointer = self.modules.get(name)
        if not pointer:
            try:
                pointer = self.py.lookup(self.module_pointer, name)
                self.modules[name] = pointer
            except KeyError:
                return {}
        return self.py.lazy_mapping(self.reader.u64(pointer + 16))

    def prepare(self) -> None:
        self.reader.cache.clear()
        maps = self.adb.shell(f'cat /proc/{self.pid}/maps')
        library = next((line.split() for line in maps.splitlines() if '/libclient.so' in line), None)
        if not library or int(library[0].split('-')[0], 16) - int(library[2], 16) != self.base:
            raise ConnectionError('游戏进程发生变化')
        self.reader.update_maps(maps)
        self.refresh_modules()
        self.globals = self.module('Globals')
        pointer = self.globals.get('player1')
        if not pointer or self.py.kind(pointer) == 'NoneType':
            raise RuntimeError('等待角色登录')
        if getattr(self, '_player_pointer', pointer) != pointer:
            self.config_cache.clear()
            self.__dict__.pop('_race_rows', None)
        self._player_pointer = pointer
        self.player = self.py.lazy_attrs(pointer)
        self.params = self.py.lazy_mapping(self.player['recordparam'])
        self.initial_data = self.py.lazy_mapping(self.player['_init_bdict']) if '_init_bdict' in self.player else {}

    def value(self, key: str, default=None):
        return self.py.decode(self.player[key]) if key in self.player else default

    def param(self, key: str, default=None):
        return self.py.decode(self.params[key]) if key in self.params else default

    def initial(self, key: str, default=None):
        return self.py.decode(self.initial_data[key]) if key in self.initial_data else default

    def module_value(self, name: str, key: str, default=None):
        module = self.module(name)
        return self.py.decode(module[key]) if key in module else default

    def config(self, name: str, key: int):
        cached = self.config_cache.get((name, key))
        if cached and time.monotonic() - cached[0] < (60 if cached[1] is not None else 5):
            return cached[1]
        value = self._read_config(name, key)
        self.config_cache[(name, key)] = (time.monotonic(), value)
        return value

    def _read_config(self, name: str, key: int):
        mod = self.module(name)
        if 'data' not in mod:
            return None
        proxy = self.py.attrs(mod['data'])
        bind = proxy.get('bindict_data')
        if not bind:
            return None
        direct = self.reader.u64(bind + 24)
        if direct:
            mapping = self.py.lazy_mapping(direct)
            pointer = mapping.get(key)
            return self.py.decode(pointer) if pointer else None
        native = self.reader.u64(bind + 16)
        if not native:
            return None
        sentinel, node = native + 88, self.reader.u64(native + 96)
        seen = set()
        while node and node != sentinel and node not in seen and len(seen) < 300:
            seen.add(node)
            value = self.reader.u64(node + 24)
            if value and self.py.kind(value) == 'taggeddict.taggeddict':
                field = 'CellID' if name.endswith('.shop') else 'id'
                try:
                    matches = self.py.tagged_value(value, field) == key
                except KeyError:
                    matches = False
                if matches:
                    return self.py.decode(value)
            node = self.reader.u64(node + 8)
        return None

    def param_names(self) -> dict:
        mod = self.module('com.param_def')
        if 'ParamNameDef' not in mod:
            return {}
        return {k: self.py.atom(v) for k, v in self.py.entries(self.reader.u64(mod['ParamNameDef'] + 264))
                if isinstance(k, str) and not k.startswith('_')}

    def cached_configs(self, name: str, limit: int = 500) -> list[dict]:
        """Inspect only rows already materialized by the client; no requests or evaluation."""
        mod = self.module(name)
        if 'data' not in mod:
            return []
        bind = self.py.attrs(mod['data']).get('bindict_data')
        if not bind:
            return []
        direct = self.reader.u64(bind + 24)
        result = []
        if direct:
            for key, value in self.py.entries(direct)[:limit]:
                row = self.py.decode(value)
                if isinstance(row, dict):
                    result.append(row)
            return result
        native = self.reader.u64(bind + 16)
        if not native:
            return []
        sentinel, node = native + 88, self.reader.u64(native + 96)
        seen = set()
        while node and node != sentinel and node not in seen and len(seen) < limit:
            seen.add(node)
            value = self.reader.u64(node + 24)
            if value and self.py.kind(value) == 'taggeddict.taggeddict':
                row = self.py.decode(value)
                if isinstance(row, dict):
                    result.append(row)
            node = self.reader.u64(node + 8)
        return result

    def close(self) -> None:
        self.reader.close()


class LiveDict(Mapping):
    def __init__(self, py: PythonObjects, address: int):
        self.py, self.address = py, address

    def __getitem__(self, key):
        if isinstance(key, (str, int)):
            return self.py.lookup(self.address, key)
        return self.py.mapping(self.address)[key]

    def __iter__(self):
        return (key for key, _ in self.py.entries(self.address))

    def __len__(self):
        return self.py.r.i64(self.address + 16)
