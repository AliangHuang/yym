"""Data-only portable smoke check. Does not operate the game or inspect screen pixels."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from yym.geometry import Rect, dock
from yym.mumu import Adb, NO_WINDOW, discover_install, discover_instances
from yym.storage import atomic_json, data_dir
from yym.windowing import enable_dpi, target_geometry, process_id, place, window_rect, user


def windows():
    user = ctypes.WinDLL('user32')
    user.GetWindow.argtypes, user.GetWindow.restype = [w.HWND, w.UINT], w.HWND
    user.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    result = []
    callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def callback(hwnd, unused):
        text = ctypes.create_unicode_buffer(256)
        user.GetWindowTextW(hwnd, text, 256)
        if text.value.startswith('痒痒猫'):
            rect = w.RECT()
            user.GetWindowRect(hwnd, ctypes.byref(rect))
            result.append({'hwnd': int(hwnd), 'visible': bool(user.IsWindowVisible(hwnd)),
                           'owner': int(user.GetWindow(hwnd, 4) or 0),
                           'title': text.value, 'pid': process_id(hwnd),
                           'rect': [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top]})
        return True
    callback_object = callback_type(callback)
    user.EnumWindows(callback_object, 0)
    return result


def verify_interaction(instances, pid):
    """Move/minimize only emulator frames; always restore original bounds."""
    records = []
    def panel_for(instance):
        title = '痒痒猫 · ' + instance.name
        return next((p for p in windows() if p['pid'] == pid and p['title'] in {title, title + ' - 痒痒猫'}), None)
    def matches(instance):
        panel, geometry = panel_for(instance), target_geometry(instance.hwnd)
        if not panel or not panel['visible'] or not geometry:
            return False
        target, work, scale = geometry
        wanted = dock(target, work, round(300 * scale), gap=round(6 * scale)).rect
        return panel['rect'] == [wanted.x, wanted.y, wanted.width, wanted.height]
    def wait_for(predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.05)
        raise AssertionError('Live sidebar did not reach the expected native window state')
    for instance in instances:
        original = window_rect(instance.hwnd)
        try:
            _, work, _ = target_geometry(instance.hwnd)
            dx = 24 if original.x + original.width + 24 <= work.x + work.width else -24
            moved = Rect(original.x + dx, original.y, original.width, original.height)
            place(instance.hwnd, moved, original)
            wait_for(lambda: matches(instance))
            user.ShowWindow(instance.hwnd, 6)
            wait_for(lambda: panel_for(instance) is not None and not panel_for(instance)['visible'])
            for sibling in instances:
                if sibling.index != instance.index:
                    assert matches(sibling), 'Minimizing one emulator affected its sibling sidebar'
            user.ShowWindow(instance.hwnd, 4)
            wait_for(lambda: matches(instance))
        finally:
            if user.IsIconic(instance.hwnd):
                user.ShowWindow(instance.hwnd, 4)
            place(instance.hwnd, original)
        wait_for(lambda: matches(instance))
        assert window_rect(instance.hwnd) == original
        records.append({'instance': instance.index, 'move_follow': True, 'independent_minimize_restore': True,
                        'original_bounds_restored': True})
    return records


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--seconds', type=int, default=35)
    parser.add_argument('--interaction', action='store_true', help='Temporarily move/minimize emulator frames and restore them')
    parser.add_argument('--output', type=Path, default=Path('build/validation.json'))
    args = parser.parse_args()
    enable_dpi()
    install = discover_install()
    instances = discover_instances(install)
    if not instances:
        raise SystemExit('No running MuMu instances')
    adbs = {i.index: Adb(str(install / 'adb.exe'), i.serial) for i in instances}
    before = {index: adb.shell('id -u') for index, adb in adbs.items()}
    minimized = [i.hwnd for i in instances if user.IsIconic(i.hwnd)]
    # Restore only for coordinate verification, then return to the original state.
    for hwnd in minimized:
        user.ShowWindow(hwnd, 9)
    baseline = time.time()
    executable = args.executable.resolve()
    env = {k: v for k, v in os.environ.items() if k not in ['PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'QT_QPA_PLATFORM']}
    env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    process = subprocess.Popen([str(executable), '--smoke-seconds', str(args.seconds)], cwd=executable.parent,
                               env=env, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    seen, latest, bindings, last_windows, interaction = {}, {}, [], [], []
    try:
        while process.poll() is None and time.time() - baseline < args.seconds + 30:
            for file in (data_dir() / 'accounts').glob('*/latest.json'):
                try:
                    if file.stat().st_mtime < baseline:
                        continue
                    value = json.loads(file.read_text(encoding='utf-8'))
                    index = value['instance']
                    seen.setdefault(index, set()).add(value['checked_at'])
                    latest[index] = value
                except (OSError, ValueError, KeyError):
                    continue
            active = windows()
            if active:
                last_windows = active
            candidate = []
            for instance in instances:
                geometry = target_geometry(instance.hwnd)
                title = '痒痒猫 · ' + instance.name
                panels = [p for p in active if p['pid'] == process.pid and p['title'] in {title, title + ' - 痒痒猫'}]
                if geometry and len(panels) == 1:
                    target, work, scale = geometry
                    expected = dock(target, work, round(300 * scale), gap=round(6 * scale))
                    actual = panels[0]['rect']
                    wanted = [expected.rect.x, expected.rect.y, expected.rect.width, expected.rect.height]
                    candidate.append({'instance': instance.index, 'side': expected.side,
                                      'collapsed': expected.collapsed, 'coordinate_match': actual == wanted,
                                      'independent_input_queue': panels[0]['owner'] == 0 or process_id(panels[0]['owner']) == process.pid,
                                      'actual_rect': actual, 'expected_rect': wanted})
            if len(candidate) == len(instances):
                bindings = candidate
                if args.interaction and not interaction and time.time() - baseline > 5 and all(b['coordinate_match'] for b in bindings):
                    interaction = verify_interaction(instances, process.pid)
            time.sleep(1)
        process.wait(timeout=15)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        for hwnd in minimized:
            user.ShowWindow(hwnd, 6)
    after = {index: adb.shell('id -u') for index, adb in adbs.items()}
    accounts = [(v['account']['server'], v['account']['uid']) for v in latest.values()]
    report = {
        'mode': 'portable-data-only', 'exit_code': process.returncode,
        'snapshots': {key: len(values) for key, values in seen.items()},
        'latest_duration_ms': {key: value['duration_ms'] for key, value in latest.items()},
        'distinct_accounts': len(set(accounts)) == len(instances), 'bindings': bindings,
        'last_windows': last_windows,
        'permissions_restored': before == after,
        'task_count': {key: len(value['tasks']) for key, value in latest.items()},
        'original_window_state_restored': True,
        'window_interaction': interaction,
    }
    atomic_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert process.returncode == 0
    assert set(seen) == set(adbs) and all(len(v) >= 3 for v in seen.values())
    assert report['distinct_accounts'] and report['permissions_restored']
    assert len(bindings) == len(instances) and all(b['coordinate_match'] for b in bindings)
    assert all(b['independent_input_queue'] for b in bindings)
    if args.interaction:
        assert len(interaction) == len(instances)


if __name__ == '__main__':
    main()
