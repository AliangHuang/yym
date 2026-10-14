from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time

from yym.collector import collect
from yym.memory import GameSession, UnsupportedClient
from yym.models import Snapshot
from yym.mumu import Adb, RootLease
from yym.storage import save_snapshot, setup_logging

log = logging.getLogger(__name__)


def pipe_stdio() -> None:
    if sys.stdin is not None and sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
        sys.stdin.reconfigure(encoding='utf-8')
        return
    import ctypes
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [ctypes.c_uint32]
    kernel.GetStdHandle.restype = ctypes.c_void_p
    for attr, constant, mode, flag in [('stdin', -10, 'r', os.O_RDONLY), ('stdout', -11, 'w', os.O_WRONLY)]:
        handle = kernel.GetStdHandle(constant & 0xFFFFFFFF)
        fd = msvcrt.open_osfhandle(handle, flag | os.O_BINARY)
        setattr(sys, attr, os.fdopen(fd, mode, encoding='utf-8', buffering=1))


def worker_main(adb_path: str, serial: str, instance: str) -> int:
    pipe_stdio()
    setup_logging('yym-worker-' + ''.join(c for c in instance if c.isascii() and c.isalnum()) + '.log')
    stop, wake = threading.Event(), threading.Event()
    paused = threading.Event()
    output_lock = threading.Lock()

    def send(kind, **payload):
        with output_lock:
            try:
                print(json.dumps({'kind': kind, **payload}, ensure_ascii=False), flush=True)
            except (BrokenPipeError, OSError):
                stop.set()

    def commands():
        try:
            for line in sys.stdin:
                try:
                    command = json.loads(line)
                    kind = command.get('type')
                    if kind == 'stop':
                        stop.set()
                    elif kind == 'pause':
                        paused.set() if command.get('paused') else paused.clear()
                    wake.set()
                except (ValueError, AttributeError):
                    pass
        finally:
            log.info('Parent input closed instance=%s', instance)
            stop.set()
            wake.set()

    threading.Thread(target=commands, daemon=True, name='yym-parent-watch').start()
    adb = Adb(adb_path, serial)
    lease = RootLease(adb, lambda owned: send('lease', owned=owned))
    session = None
    backoff = 1.0
    try:
        while not stop.is_set():
            if paused.is_set():
                wake.wait(1)
                wake.clear()
                continue
            start = time.monotonic()
            try:
                if session is None:
                    send('connection', state='connecting', message='正在连接并校验客户端')
                    lease.acquire()
                    pid, maps = GameSession.find(adb)
                    send('connection', state='connecting', message='正在首次加载角色数据，请稍候')
                    session = GameSession(adb, pid, maps, cancel=stop)
                    log.info('Session attached instance=%s duration=%.2f', instance, time.monotonic() - start)
                # A cheap pid check prevents using addresses from a restarted game.
                if not adb.shell(f'test -d /proc/{session.pid} && echo alive', timeout=5).endswith('alive'):
                    raise ConnectionError('游戏进程已重启')
                snapshot = collect(session, instance)
                snapshot.duration_ms = round((time.monotonic() - start) * 1000)
                save_snapshot(snapshot)
                send('snapshot', snapshot=snapshot.to_dict())
                log.debug('Snapshot delivered instance=%s duration=%s', instance, snapshot.duration_ms)
                backoff = 1.0
                delay = max(0.2, 5 - (time.monotonic() - start))
            except Exception as exc:
                if stop.is_set():
                    break
                if session:
                    session.close()
                    session = None
                unsupported = isinstance(exc, UnsupportedClient)
                text = str(exc)[:200] if isinstance(exc, (UnsupportedClient, PermissionError)) else '连接或读取中断，正在重试'
                log.warning('Read failure instance=%s type=%s', instance, type(exc).__name__)
                send('connection', state='unsupported' if unsupported else 'offline', message=text)
                delay = 30 if unsupported else min(backoff, 15)
                backoff = min(backoff * 2, 15)
            wake.wait(delay)
            wake.clear()
    finally:
        if session:
            session.close()
        try:
            lease.close()
        except Exception:
            log.exception('Could not restore ADB permission for instance=%s', instance)
            send('cleanup_error', message='读取权限恢复失败，请在连接恢复后重试退出')
    return 0
