"""Exercise native window coordinates and Qt controls using disposable test windows."""
import ctypes
from ctypes import wintypes as w
import json
from pathlib import Path
import time

from yym.geometry import Rect, dock
from yym.models import Instance
from yym import windowing
from yym.storage import atomic_json


def main():
    windowing.enable_dpi()
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtCore import Qt
    from yym.ui import Panel, STYLE, app_icon
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)
    class Manager:
        settings = {}
        icon = app_icon()
        def save(self):
            pass
    class Runner:
        def command(self, *args, **kwargs):
            pass
    monitors = []
    callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HMONITOR, w.HDC, ctypes.POINTER(w.RECT), w.LPARAM)
    def found(handle, dc, rect, unused):
        monitors.append(Rect(rect.contents.left, rect.contents.top,
                             rect.contents.right - rect.contents.left, rect.contents.bottom - rect.contents.top))
        return True
    cb = callback_type(found)
    windowing.user.EnumDisplayMonitors(None, None, cb, 0)
    target = QWidget(None, Qt.WindowType.FramelessWindowHint)
    target.setWindowTitle('yym-window-test')
    target.show()
    panel = Panel(Manager(), Instance('test', 'yym-test', int(target.winId()), 0, ''), Runner())
    records = []
    def settle():
        for _ in range(6):
            app.processEvents()
            panel.follow()
            time.sleep(0.04)
    try:
        for monitor in monitors:
            windowing.place(int(target.winId()), Rect(monitor.x + 400, monitor.y + 100, 500, 500))
            settle()
            _, work, scale = windowing.target_geometry(int(target.winId()))
            width, height = min(round(500 * scale), work.width // 2), min(round(500 * scale), work.height - 100)
            cases = [('left', Rect(work.x + round(400 * scale), work.y + 50, width, height)),
                     ('right', Rect(work.x + 20, work.y + 50, width, height)),
                     ('compact', Rect(work.x, work.y, work.width, work.height))]
            for name, position in cases:
                windowing.place(int(target.winId()), position)
                settle()
                actual_target, current_work, current_scale = windowing.target_geometry(int(target.winId()))
                expected = dock(actual_target, current_work, round(300 * current_scale), gap=round(6 * current_scale))
                actual = windowing.window_rect(int(panel.winId()))
                assert actual == expected.rect, (name, actual, expected)
                assert panel.compact.isVisible() == expected.collapsed
                assert expected.side == name or name == 'compact'
                records.append({'case': name, 'dpi_scale': current_scale, 'passed': True})
            windowing.user.ShowWindow(int(target.winId()), 6)
            settle()
            assert not panel.isVisible()
            windowing.user.ShowWindow(int(target.winId()), 9)
            settle()
            assert panel.isVisible()
        report = {'monitors': len(monitors), 'cases': records, 'minimize_restore': True,
                  'inspection': 'Qt control state and native coordinates; no images'}
        atomic_json(Path('build/docking-validation.json'), report)
        print(json.dumps(report, indent=2))
    finally:
        panel.close()
        target.close()
        app.processEvents()


if __name__ == '__main__':
    main()
