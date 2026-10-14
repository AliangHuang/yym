"""Kill a test-owned reader and verify permission cleanup and reconnection; no game actions."""
import json
from pathlib import Path
import time

from yym.mumu import Adb, discover_install, discover_instances
from yym.storage import atomic_json, setup_logging
from yym.windowing import enable_dpi


def main():
    enable_dpi()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QProcess, QTimer
    from yym.ui import Manager, STYLE
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)
    setup_logging()
    install = discover_install()
    instances = discover_instances(install)
    adbs = {i.index: Adb(str(install / 'adb.exe'), i.serial) for i in instances}
    before = {key: adb.shell('id -u') for key, adb in adbs.items()}
    assert before and all(uid == '2000' for uid in before.values()), 'Test requires originally unrooted ADB'
    manager = Manager(app, install)
    state = {'phase': 'connect', 'passed': False}
    def check():
        if not manager.runners:
            return
        r = manager.runners.get('0') or next(iter(manager.runners.values()))
        if state['phase'] == 'connect' and all(x.panel.last_received for x in manager.runners.values()):
            state.update(phase='cleanup', old_pid=r.process.processId(), account=r.panel.snapshot.account.key)
            r.panel.pause.setChecked(True)
            r.process.kill()
        elif state['phase'] == 'cleanup' and r.process.state() == QProcess.ProcessState.NotRunning and not r.root_owned and not r.cleanup_busy:
            assert adbs[r.instance.index].shell('id -u') == before[r.instance.index]
            state.update(phase='reconnect', since=time.monotonic())
            r.panel.pause.setChecked(False)
            manager.discover()
        elif state['phase'] == 'reconnect' and r.panel.last_received > state['since']:
            assert r.process.processId() != state['old_pid']
            assert r.panel.snapshot.account.key == state['account']
            state.update(phase='done', passed=True)
            app.quit()
    timer = QTimer()
    timer.timeout.connect(check)
    timer.start(500)
    QTimer.singleShot(60000, app.quit)
    app.exec()
    after = {key: adb.shell('id -u') for key, adb in adbs.items()}
    report = {'reader_crash_recovered': state['passed'], 'permissions_restored': before == after,
              'account_preserved': state['passed'], 'inspection': 'worker IPC and ADB UID; no images'}
    atomic_json(Path('build/recovery-validation.json'), report)
    print(json.dumps(report, indent=2))
    assert state['passed'] and before == after


if __name__ == '__main__':
    main()
