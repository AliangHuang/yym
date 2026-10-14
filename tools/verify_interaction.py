"""Two-instance native interaction regression using disposable windows, never game input."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch

from yym import windowing
from yym.geometry import Rect, dock
from yym.models import Instance
from yym.storage import atomic_json


def main():
    windowing.enable_dpi()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from yym.ui import Panel, STYLE, app_icon
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    if '--targets' in sys.argv:
        from PySide6.QtCore import QObject, Signal
        class Stop(QObject):
            requested = Signal()
        stop = Stop()
        stop.requested.connect(app.quit)
        windows = [QWidget(None, Qt.WindowType.FramelessWindowHint) for _ in range(2)]
        for index, widget in enumerate(windows):
            widget.setWindowTitle('yym-interaction-target-' + str(index))
            widget.show()
        app.processEvents()
        print(json.dumps([int(t.winId()) for t in windows]), flush=True)
        def read_stdin():
            sys.stdin.buffer.read()
            stop.requested.emit()
        threading.Thread(target=read_stdin, daemon=True).start()
        app.exec()
        return
    app.setStyleSheet(STYLE)
    user = windowing.user
    user.WindowFromPoint.argtypes, user.WindowFromPoint.restype = [w.POINT], w.HWND
    user.SetForegroundWindow.argtypes = [w.HWND]
    user.SetActiveWindow.argtypes, user.SetActiveWindow.restype = [w.HWND], w.HWND
    user.SetFocus.argtypes, user.SetFocus.restype = [w.HWND], w.HWND
    user.GetActiveWindow.restype = w.HWND
    user.GetFocus.restype = w.HWND
    user.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user.ScreenToClient.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
    user.IsWindowEnabled.argtypes = [w.HWND]
    native_foreground = user.GetForegroundWindow
    original_foreground = int(native_foreground() or 0)
    flags = 0x0010 | 0x0001 | 0x0002 | 0x0200

    class Manager:
        def __init__(self):
            self.settings, self.icon = {}, app_icon()
        def save(self):
            pass

    class Runner:
        def __init__(self):
            self.calls = []
        def command(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    targets, panels, runners = [], [], []
    child = None
    outsider = QWidget(None, Qt.WindowType.FramelessWindowHint)
    outsider.setWindowTitle('yym-test-unrelated-app')
    records, focus_modes = [], []

    def pump(count=5):
        for _ in range(count):
            app.processEvents()
            time.sleep(.005)

    def settle(order=(0, 1)):
        for _ in range(3):
            for index in order:
                panels[index].follow()
            pump()

    def topmost(widget):
        return bool(user.GetWindowLongPtrW(int(widget.winId()), -20) & 8)

    @contextmanager
    def foreground(widget):
        hwnd = int(widget.winId())
        user.SetForegroundWindow(hwnd)
        pump()
        if int(native_foreground() or 0) == hwnd:
            focus_modes.append('native-activation')
            yield
        else:
            # Windows may deny foreground changes while the user is working.
            # Preserve real HWND ordering/hits/messages; control only this read.
            if windowing.process_id(hwnd) == os.getpid():
                user.SetActiveWindow(hwnd)
                user.SetFocus(hwnd)
                pump()
                assert int(user.GetActiveWindow() or 0) == hwnd
                assert int(user.GetAncestor(user.GetFocus(), 2) or 0) == hwnd
                focus_modes.append('native-thread-focus-controlled-foreground-identity')
            else:
                focus_modes.append('controlled-foreground-identity')
            with patch.object(user, 'GetForegroundWindow', return_value=hwnd):
                yield

    def button_click(index, require_front=True):
        panel = panels[index]
        hwnd = int(panel.winId())
        local = panel.refresh.mapTo(panel, panel.refresh.rect().center())
        rect = windowing.window_rect(hwnd)
        scale = user.GetDpiForWindow(hwnd) / 96
        point = w.POINT(rect.x + round(local.x() * scale), rect.y + round(local.y() * scale))
        def hit():
            return int(user.GetAncestor(user.WindowFromPoint(point), 2) or 0)
        if require_front:
            assert hit() == hwnd, ('hit before down', index, hit(), hwnd)
        before = [len(r.calls) for r in runners]
        client = w.POINT(point.x, point.y)
        user.ScreenToClient(hwnd, ctypes.byref(client))
        packed = (client.x & 0xffff) | ((client.y & 0xffff) << 16)
        user.PostMessageW(hwnd, 0x0201, 1, packed)
        pump()
        settle((1, 0))
        if require_front:
            assert hit() == hwnd, ('hit between down/up', index, hit(), hwnd)
        user.PostMessageW(hwnd, 0x0202, 0, packed)
        pump()
        counts = [len(r.calls) - before[i] for i, r in enumerate(runners)]
        assert counts[index] == 1 and counts[1 - index] == 0, counts
        return counts

    def check_geometry(index):
        geometry = windowing.target_geometry(int(targets[index].winId()))
        target, work, scale = geometry
        expected = dock(target, work, round(300 * scale), gap=round(6 * scale))
        assert windowing.window_rect(int(panels[index].winId())) == expected.rect

    try:
        child = subprocess.Popen([sys.executable, __file__, '--targets'], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        handles = json.loads(child.stdout.readline())
        class Target:
            def __init__(self, hwnd):
                self.hwnd = hwnd
            def winId(self):
                return self.hwnd
        for index in range(2):
            target = Target(handles[index])
            runner = Runner()
            panel = Panel(Manager(), Instance(str(index), 'yym-test-' + str(index), int(target.winId()), 0, ''), runner)
            targets.append(target)
            panels.append(panel)
            runners.append(runner)
        outsider.show()
        pump()
        _, work, scale = windowing.target_geometry(int(targets[0].winId()))
        base = Rect(work.x + round(450 * scale), work.y + 80,
                    min(round(480 * scale), work.width // 3), min(round(480 * scale), work.height - 150))
        windowing.place(int(outsider.winId()), Rect(work.x + work.width - 150, work.y, 140, 100))
        for target in targets:
            windowing.place(int(target.winId()), base)
        settle()

        # Full and partial overlap, both foreground panels and update orders.
        for offset in (0, round(50 * scale)):
            windowing.place(int(targets[1].winId()), Rect(base.x + offset, base.y, base.width, base.height))
            for order in ((0, 1), (1, 0)):
                for index in (0, 1):
                    front, rear = panels[index], panels[1 - index]
                    user.SetWindowPos(int(rear.winId()), w.HWND(-2), 0, 0, 0, 0, flags)
                    user.SetWindowPos(int(front.winId()), w.HWND(-1), 0, 0, 0, 0, flags)
                    with foreground(front):
                        settle(order)
                        counts = button_click(index)
                        assert topmost(front) and not topmost(rear)
                    records.append({'case': 'overlap-click', 'offset_px': offset, 'front': index,
                                    'update_order': order, 'clicks': counts})

        for index in (0, 1):
            with foreground(targets[index]):
                settle()
                assert topmost(panels[index]) and not topmost(panels[1 - index])
            records.append({'case': 'target-focus', 'instance': index})
        with foreground(outsider):
            settle()
            assert not any(topmost(p) for p in panels)
            for i in range(2):
                assert int(user.GetWindow(int(panels[i].winId()), 3) or 0) == int(targets[i].winId())
        records.append({'case': 'unrelated-window-focus'})

        # One settings dialog must never block another instance's refresh button.
        panels[0].open_preferences()
        dialog = panels[0].preferences_dialog
        pump()
        assert dialog.isVisible() and dialog.windowModality() == Qt.WindowModality.WindowModal
        assert not user.IsWindowEnabled(int(panels[0].winId()))
        assert user.IsWindowEnabled(int(panels[1].winId()))
        with foreground(panels[1]):
            settle()
            assert topmost(panels[1]) and not topmost(panels[0])
            button_click(1)
        with foreground(dialog):
            settle()
            assert topmost(panels[0]) and not topmost(panels[1]), {
                'focus': int(user.GetForegroundWindow() or 0), 'dialog': int(dialog.winId()),
                'dialog_owner': int(user.GetWindow(int(dialog.winId()), 4) or 0),
                'panels': [int(p.winId()) for p in panels],
                'panel_owners': [int(user.GetWindow(int(p.winId()), 4) or 0) for p in panels],
                'topmost': [topmost(p) for p in panels]}
        records.append({'case': 'settings-focus-and-sibling-input'})

        # Two dialogs stay independent; minimize/hide/recover each instance.
        panels[1].open_preferences()
        dialogs = [p.preferences_dialog for p in panels]
        for dialog in dialogs:
            dialog.items.item(0).setCheckState(Qt.CheckState.Unchecked)
        for index in (0, 1):
            other = 1 - index
            with foreground(dialogs[other]):
                settle()
                user.ShowWindow(int(targets[index].winId()), 6)
                settle()
                assert not panels[index].isVisible() and not dialogs[index].isVisible()
                assert panels[other].isVisible() and dialogs[other].isVisible()
                assert not user.IsWindowVisible(int(dialogs[index].winId()))
                # SW_MINIMIZE itself may activate a different window. Establish
                # focus again before testing our no-activation restore path.
                user.SetActiveWindow(int(dialogs[other].winId()))
                user.SetFocus(int(dialogs[other].winId()))
                pump()
                before_focus = int(native_foreground() or 0)
                before_thread_focus = int(user.GetFocus() or 0)
                user.ShowWindow(int(targets[index].winId()), 4)
                settle()
                assert panels[index].isVisible() and dialogs[index].isVisible()
                assert dialogs[index].items.item(0).checkState() == Qt.CheckState.Unchecked
                assert int(native_foreground() or 0) == before_focus
                assert int(user.GetFocus() or 0) == before_thread_focus, {
                    'instance': index, 'before': before_thread_focus,
                    'after_restore': int(user.GetFocus() or 0), 'active': int(user.GetActiveWindow() or 0),
                    'dialogs': [int(d.winId()) for d in dialogs], 'panels': [int(p.winId()) for p in panels]}
                check_geometry(index)
            records.append({'case': 'independent-minimize-restore-with-unsaved-settings', 'instance': index})
        for dialog in dialogs:
            dialog.reject()
        pump()
        for index in (0, 1):
            user.ShowWindow(int(targets[index].winId()), 0)
            settle()
            assert not panels[index].isVisible() and panels[1 - index].isVisible()
            user.ShowWindow(int(targets[index].winId()), 4)
            settle()
            assert all(p.isVisible() for p in panels)
            assert panels[index].preferences_dialog is None
        records.append({'case': 'independent-hide-show-no-dialog-reopened'})

        # An emulator with its own topmost option must stabilize in that band.
        with foreground(outsider):
            user.SetWindowPos(int(targets[0].winId()), w.HWND(-1), 0, 0, 0, 0, flags)
            settle()
            assert topmost(panels[0])
            calls = []
            original = user.SetWindowPos
            def observe(*args):
                calls.append(args)
                return original(*args)
            with patch.object(user, 'SetWindowPos', side_effect=observe):
                for _ in range(40):
                    settle()
            assert not calls, ('repeated topmost/geometry writes', len(calls))
            user.SetWindowPos(int(targets[0].winId()), w.HWND(-2), 0, 0, 0, 0, flags)
            settle()
            assert not any(topmost(p) for p in panels)
        records.append({'case': 'topmost-toggle', 'idle_follow_rounds': 120, 'redundant_native_writes': 0})

        owners = [int(user.GetWindow(int(p.winId()), 4) or 0) for p in panels]
        assert all(not owner or windowing.process_id(owner) == os.getpid() for owner in owners)
        report = {'cases': records, 'case_count': len(records), 'foreground_modes': focus_modes,
                  'independent_input_queues': True,
                  'inspection': 'native HWND, z-order, control events and visibility; no images or game input'}
        atomic_json(Path('build/interaction-validation.json'), report)
        print(json.dumps(report, indent=2))
    finally:
        for panel in panels:
            panel.close()
        if child is not None:
            child.stdin.close()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        outsider.close()
        pump()
        # Only restore focus if it still belongs to one of our disposable windows.
        if windowing.process_id(int(user.GetForegroundWindow() or 0)) == windowing.process_id(int(outsider.winId())):
            if user.IsWindow(original_foreground):
                user.SetForegroundWindow(original_foreground)


if __name__ == '__main__':
    main()
