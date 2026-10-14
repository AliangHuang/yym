"""Cross-process movement regression; disposable windows, no game or screen reads."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from yym.geometry import Rect
from yym import windowing
from yym.storage import atomic_json


def main():
    windowing.enable_dpi()
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from yym.ui import FollowScheduler, Panel, STYLE, app_icon
    from yym.models import Instance
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    if '--target' in sys.argv:
        targets = [QWidget(None, Qt.WindowType.FramelessWindowHint) for _ in range(2)]
        for index, target in enumerate(targets):
            target.setWindowTitle('yym-motion-test-' + str(index))
            target.resize(500, 400)
            target.show()
        app.processEvents()
        handles = [int(target.winId()) for target in targets]
        for index, hwnd in enumerate(handles):
            windowing.place(hwnd, Rect(700 + index * 120, 200 + index * 120, 500, 400))
        print(json.dumps({'hwnds': handles}), flush=True)
        ticks = []
        def tick():
            index = len(ticks)
            for number, hwnd in enumerate(handles):
                windowing.place(hwnd, Rect(700 + number * 120 + index % 200,
                                          200 + number * 120 + index % 80, 500, 400))
            ticks.append(time.time())
        timer = QTimer()
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.timeout.connect(tick)
        timer.start(8)
        QTimer.singleShot(5000, app.quit)
        app.exec()
        print(json.dumps({'ticks': ticks}), flush=True)
        return
    app.setStyleSheet(STYLE)
    child = subprocess.Popen([sys.executable, __file__, '--target'], stdout=subprocess.PIPE,
                             stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    hooks, scheduler, panels = None, None, []
    frames, requests, stalls = [], [], []
    try:
        handles = json.loads(child.stdout.readline())['hwnds']
        results = []
        reader = threading.Thread(target=lambda: results.append(child.stdout.readline()), daemon=True)
        reader.start()
        class Manager:
            settings = {}
            icon = app_icon()
            def save(self):
                pass
        class Runner:
            def command(self, *args, **kwargs):
                pass
        panels = [Panel(Manager(), Instance(str(i), 'yym-motion-' + str(i), hwnd, 0, ''), Runner())
                  for i, hwnd in enumerate(handles)]
        def follow(handles):
            start = time.perf_counter()
            for panel in panels:
                if panel.instance.hwnd in handles:
                    panel.follow()
            frames.append((time.perf_counter() - start) * 1000)
        scheduler = FollowScheduler(follow)
        scheduler.set_targets(handles)
        def request(handle):
            requests.append(handle)
            scheduler.request(handle)
        hooks = windowing.WindowHooks(request)
        hooks.set_targets(handles)
        scheduler.request()
        def stall():
            start = time.time()
            time.sleep(0.2)
            stalls.append((start, time.time()))
        QTimer.singleShot(2200, stall)
        poll = QTimer()
        poll.timeout.connect(lambda: app.quit() if child.poll() is not None else None)
        poll.start(50)
        QTimer.singleShot(12000, app.quit)
        app.exec()
        child.wait(timeout=5)
        reader.join(timeout=2)
        ticks = json.loads(results[0])['ticks']
        during_stall = sum(a + 0.03 < t < b - 0.03 for a, b in stalls for t in ticks)
        owners = [int(windowing.user.GetWindow(int(panel.winId()), 4) or 0) for panel in panels]
        report = {'instances': len(panels), 'target_movements_per_instance': len(ticks), 'hook_notifications': len(requests),
                  'follow_frames': len(frames), 'follow_p95_ms': round(sorted(frames)[int(len(frames) * .95)], 2),
                  'independent_window': all(not owner or windowing.process_id(owner) == windowing.process_id(int(panel.winId()))
                                            for owner, panel in zip(owners, panels)),
                  'target_movements_during_200ms_sidebar_stall': during_stall,
                  'inspection': 'cross-process window coordinates and timer timestamps; no images'}
        atomic_json(Path('build/follow-validation.json'), report)
        print(json.dumps(report, indent=2))
        assert child.returncode == 0 and len(ticks) >= 150
        assert report['independent_window'] and during_stall >= 5
        assert len(frames) < len(ticks) and len(frames) < 350
    finally:
        if hooks:
            hooks.close()
        if scheduler:
            scheduler.stop()
        for panel in panels:
            panel.close()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


if __name__ == '__main__':
    main()
