from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='yym', description='痒痒猫 · 阴阳师日常与周常')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--adb', default='')
    parser.add_argument('--serial', default='')
    parser.add_argument('--instance', default='0')
    parser.add_argument('--mumu-dir', default='')
    parser.add_argument('--list-instances', action='store_true')
    parser.add_argument('--once', action='store_true', help='Read one snapshot, restoring temporary root afterwards')
    parser.add_argument('--output', help='Write diagnostic JSON to this file')
    parser.add_argument('--smoke-seconds', type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        from yym.worker import worker_main
        return worker_main(args.adb, args.serial, args.instance)
    from yym.mumu import Adb, RootLease, discover_install, discover_instances
    from yym.storage import load_settings
    install = discover_install(args.mumu_dir or load_settings().get('mumu_dir', ''))
    if args.list_instances or args.once:
        if not install:
            raise SystemExit('MuMu installation not found')
        from dataclasses import asdict
        from pathlib import Path
        if args.list_instances:
            result = [asdict(i) for i in discover_instances(install)]
        else:
            from yym.collector import collect
            from yym.memory import GameSession
            instance = next(i for i in discover_instances(install) if i.index == args.instance)
            adb = Adb(str(install / 'adb.exe'), instance.serial)
            lease = RootLease(adb)
            session = None
            try:
                lease.acquire()
                pid, maps = GameSession.find(adb)
                session = GameSession(adb, pid, maps)
                result = collect(session, instance.index).to_dict()
            finally:
                if session:
                    session.close()
                lease.close()
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(text, encoding='utf-8')
        elif sys.stdout is not None:
            sys.stdout.reconfigure(encoding='utf-8')
            print(text)
        return 0
    from yym.windowing import enable_dpi
    enable_dpi()
    from PySide6.QtCore import QTimer
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication
    from yym.storage import setup_logging
    from yym.ui import Manager, STYLE
    app = QApplication(sys.argv[:1])
    app.setApplicationName('yym')
    app.setApplicationDisplayName('痒痒猫')
    app.setOrganizationName('yym')
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)
    socket = QLocalSocket()
    socket.connectToServer('yym-desktop')
    if socket.waitForConnected(250):
        socket.write(b'show\n')
        socket.waitForBytesWritten(250)
        return 0
    QLocalServer.removeServer('yym-desktop')
    singleton = QLocalServer()
    if not singleton.listen('yym-desktop'):
        return 1
    setup_logging()
    manager = Manager(app, install)
    def connection():
        incoming = singleton.nextPendingConnection()
        if incoming:
            manager.show_panels()
            incoming.disconnectFromServer()
    singleton.newConnection.connect(connection)
    if args.smoke_seconds:
        QTimer.singleShot(args.smoke_seconds * 1000, app.quit)
    return app.exec()
