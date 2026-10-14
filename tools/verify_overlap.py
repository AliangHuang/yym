"""Native hit testing and button routing for overlapping disposable sidebars; no game input."""
import ctypes
from ctypes import wintypes as w
import json
from pathlib import Path
import time
from unittest.mock import patch

from yym.geometry import Rect
from yym.models import Instance
from yym import windowing
from yym.storage import atomic_json


def main():
    windowing.enable_dpi()
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from yym.ui import Panel, STYLE, app_icon
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)
    user = windowing.user
    user.WindowFromPoint.argtypes, user.WindowFromPoint.restype = [w.POINT], w.HWND
    user.SetForegroundWindow.argtypes = [w.HWND]
    user.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user.ScreenToClient.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
    class Manager:
        settings = {}
        icon = app_icon()
        def save(self):
            pass
    class Runner:
        def __init__(self):
            self.calls = []
        def command(self, *args, **kwargs):
            self.calls.append(args)
    targets, panels, runners = [], [], []
    def pump():
        for _ in range(8):
            app.processEvents()
            time.sleep(.005)
    def hit(point):
        child = user.WindowFromPoint(point)
        return int(user.GetAncestor(child, 2) or 0)
    try:
        for index in range(2):
            target = QWidget(None, Qt.WindowType.FramelessWindowHint)
            target.setWindowTitle('yym-overlap-target-' + str(index))
            target.show()
            runner = Runner()
            panel = Panel(Manager(), Instance(str(index), 'yym-test-' + str(index), int(target.winId()), 0, ''), runner)
            panel.show()
            targets.append(target)
            panels.append(panel)
            runners.append(runner)
        pump()
        for target in targets:
            windowing.place(int(target.winId()), Rect(1100, 250, 500, 600))
        for _ in range(5):
            for panel in panels:
                panel.follow()
            pump()
        cases = []
        for index in [0, 1, 0, 1]:
            front, rear = panels[index], panels[1 - index]
            fh, rh = int(front.winId()), int(rear.winId())
            flags = 0x0010 | 0x0001 | 0x0002 | 0x0200
            user.SetWindowPos(rh, w.HWND(-2), 0, 0, 0, 0, flags)
            user.SetWindowPos(fh, w.HWND(-1), 0, 0, 0, 0, flags)
            pump()
            local = front.refresh.mapTo(front, front.refresh.rect().center())
            rect = windowing.window_rect(fh)
            scale = user.GetDpiForWindow(fh) / 96
            point = w.POINT(rect.x + round(local.x() * scale), rect.y + round(local.y() * scale))
            assert hit(point) == fh, 'Test setup did not put the intended sidebar in front'
            # Feed the foreground identity without stealing the user's focus. The
            # hit testing, window reordering and button messages remain native.
            focus = patch.object(user, 'GetForegroundWindow', return_value=fh)
            focus.start()
            # This is the same periodic stacking update that runs after activation.
            for panel in panels:
                panel.follow()
            pump()
            actual = hit(point)
            assert actual == fh, {'front_index': index, 'expected_hit': fh, 'actual_hit': actual,
                                 'foreground_input': fh,
                                 'panel_handles': [int(p.winId()) for p in panels], 'target_handles': [int(t.winId()) for t in targets],
                                 'owners': [int(user.GetWindow(int(p.winId()), 4) or 0) for p in panels],
                                 'topmost': [bool(user.GetWindowLongPtrW(int(p.winId()), -20) & 8) for p in panels]}
            before = [len(r.calls) for r in runners]
            position = w.POINT(point.x, point.y)
            user.ScreenToClient(fh, ctypes.byref(position))
            packed = (position.x & 0xffff) | ((position.y & 0xffff) << 16)
            user.PostMessageW(fh, 0x0201, 1, packed)
            pump()
            for panel in panels:
                panel.follow()
            pump()
            assert hit(point) == fh
            user.PostMessageW(fh, 0x0202, 0, packed)
            pump()
            counts = [len(r.calls) - before[i] for i, r in enumerate(runners)]
            assert counts[index] == 1 and counts[1 - index] == 0, counts
            focus.stop()
            cases.append({'front_sidebar': index, 'native_hit_stable': True, 'front_button_clicks': counts[index],
                          'rear_button_clicks': counts[1 - index]})
        report = {'cases': cases, 'inspection': 'native hit HWND, focus and test-button events; no images or game input'}
        atomic_json(Path('build/overlap-validation.json'), report)
        print(json.dumps(report, indent=2))
    finally:
        patch.stopall()
        for widget in panels + targets:
            widget.close()
        app.processEvents()


if __name__ == '__main__':
    main()
