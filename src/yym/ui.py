from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSystemTrayIcon, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from yym.geometry import dock
from yym.models import Instance, LABELS, Snapshot, Status, Task
from yym.mumu import Adb, discover_install, discover_instances
from yym.rules import CATALOG, evaluate
from yym.storage import load_settings, save_settings
from yym import windowing

COLORS = {Status.COMPLETE: '#62c5a2', Status.PENDING: '#e8bc6e', Status.IN_PROGRESS: '#a89bed',
          Status.INCOMPLETE: '#e49c8c', Status.UNKNOWN: '#8994a8', Status.UNAVAILABLE: '#8994a8', Status.MISSED: '#c9a180'}

STYLE = '''
QWidget { font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 12px; color: #e3e8f0; }
QWidget#panel { background: #141b28; border: 1px solid #344158; border-radius: 10px; }
QLabel#brand { font-size: 17px; font-weight: 700; }
QLabel#subtle { color: #94a3b8; font-size: 11px; }
QLabel#connection { color: #b5c4da; font-size: 11px; padding: 5px 0; }
QFrame#card { background: #1e2838; border: 1px solid #2b384d; border-radius: 7px; }
QLabel#title { font-size: 12px; font-weight: 600; }
QLabel#detail { color: #b4c2d6; font-size: 11px; }
QLabel#hint { color: #d6b77e; font-size: 10px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QToolButton, QPushButton { background: #253349; border: 1px solid #394b65; border-radius: 5px; padding: 4px 7px; }
QToolButton:hover, QPushButton:hover { background: #344963; }
QToolButton:disabled { color: #6c7890; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #1e2838; color: #93a5bf; padding: 7px 27px; border-radius: 5px; margin-right: 4px; }
QTabBar::tab:selected { background: #34415b; color: #fff; }
QCheckBox { spacing: 5px; font-size: 11px; }
QProgressBar { border: none; border-radius: 2px; background: #334158; max-height: 3px; }
QProgressBar::chunk { background: #9e9ad8; border-radius: 2px; }
QScrollBar:vertical { width: 6px; background: transparent; }
QScrollBar::handle:vertical { background: #40506b; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QDialog, QListWidget { background: #182232; }
QListWidget { border: 1px solid #344158; }
QListWidget::item { padding: 5px; }
QMenu { background: #1e2838; border: 1px solid #40506b; }
QMenu::item { padding: 7px 18px; }
QMenu::item:selected { background: #344963; }
'''


def app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.moveTo(10, 30)
    path.lineTo(9, 7)
    path.lineTo(26, 19)
    path.quadTo(33, 16, 40, 19)
    path.lineTo(55, 7)
    path.lineTo(54, 32)
    path.cubicTo(59, 61, 7, 62, 10, 30)
    painter.fillPath(path, QColor('#ada0e4'))
    painter.setPen(QPen(QColor('#172133'), 3))
    painter.drawLine(23, 31, 23, 36)
    painter.drawLine(42, 31, 42, 36)
    painter.drawLine(30, 40, 34, 40)
    painter.end()
    return QIcon(pixmap)


class TaskCard(QFrame):
    def __init__(self, task: Task):
        super().__init__()
        self.setObjectName('card')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 8, 9, 8)
        layout.setSpacing(5)
        top = QHBoxLayout()
        self.title = QLabel(task.title)
        self.title.setObjectName('title')
        self.badge = QLabel()
        top.addWidget(self.title, 1)
        top.addWidget(self.badge)
        layout.addLayout(top)
        self.detail = QLabel()
        self.detail.setObjectName('detail')
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self.hint = QLabel()
        self.hint.setObjectName('hint')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.update_task(task, False)

    def update_task(self, task: Task, live: bool):
        state = task.status if live else Status.UNKNOWN
        self.badge.setText(LABELS[state])
        self.badge.setStyleSheet(f'color: {COLORS[state]}; font-size: 10px;')
        self.detail.setText(task.detail if live else ('上次记录：' + task.detail if task.source else task.detail))
        self.hint.setText(('请打开：' + task.needs_page) if task.needs_page else '')
        self.hint.setVisible(bool(task.needs_page))
        has_progress = live and task.progress is not None and bool(task.target)
        self.progress.setVisible(has_progress)
        if has_progress:
            self.progress.setValue(max(0, min(1000, int(task.progress / task.target * 1000))))
        self.setToolTip(f'来源：{task.source or "尚未读取"}\n读取时间：{task.observed_at or "—"}\n所属周期：{task.period or "—"}')


class Preferences(QDialog):
    def __init__(self, panel):
        super().__init__(panel)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowTitle('痒痒猫 · 关注项目')
        self.resize(350, 570)
        self.panel = panel
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('选择要显示的项目（不改变完成状态）'))
        self.items = QListWidget()
        hidden = panel.preferences().get('hidden_tasks', [])
        for key, name, cadence, _ in CATALOG:
            item = QListWidgetItem(('日常 · ' if cadence == 'daily' else '周常 · ') + name)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked if key in hidden else Qt.CheckState.Checked)
            self.items.addItem(item)
        layout.addWidget(self.items, 1)
        layout.addWidget(QLabel('关注的周兑换商品'))
        self.shop = QListWidget()
        self.shop.setMaximumHeight(100)
        choices = panel.snapshot.choices.get('shop', []) if panel.snapshot else []
        selected = panel.preferences().get('shop_selected', ['22', '40', '42', '704', '705'])
        for offer in choices:
            item = QListWidgetItem(offer['label'])
            item.setData(Qt.ItemDataRole.UserRole, offer['id'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if selected is None or offer['id'] in selected else Qt.CheckState.Unchecked)
            self.shop.addItem(item)
        if not choices:
            self.shop.addItem('打开商店页面后加载可选商品')
            self.shop.setEnabled(False)
        layout.addWidget(self.shop)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        prefs = self.panel.preferences()
        prefs['hidden_tasks'] = [self.items.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.items.count())
                                if self.items.item(i).checkState() == Qt.CheckState.Unchecked]
        if self.shop.isEnabled():
            prefs['shop_selected'] = [self.shop.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.shop.count())
                                      if self.shop.item(i).checkState() == Qt.CheckState.Checked]
        self.panel.manager.save()
        self.panel.render()
        self.panel.runner.command('refresh')
        super().accept()


class Panel(QWidget):
    def __init__(self, manager, instance: Instance, runner):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.manager, self.instance, self.runner = manager, instance, runner
        self.snapshot = evaluate({}, instance.index)
        self.state, self.message = 'connecting', '正在连接'
        self.user_collapsed = False
        self.last_received = 0.0
        self.last_placement = None
        self.preferences_dialog = None
        self._suspended_preferences = False
        self._preferences_position = None
        self.setObjectName('panel')
        self.setWindowTitle('痒痒猫 · ' + instance.name)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowIcon(manager.icon)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 9, 8, 7)
        self.expanded = QWidget()
        layout = QVBoxLayout(self.expanded)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(manager.icon.pixmap(23, 23))
        brand = QLabel('痒痒猫')
        brand.setObjectName('brand')
        header.addWidget(logo)
        header.addWidget(brand, 1)
        settings = QToolButton()
        settings.setText('设置')
        settings.clicked.connect(self.open_preferences)
        collapse = QToolButton()
        collapse.setText('‹')
        collapse.setToolTip('折叠侧栏')
        collapse.clicked.connect(self.toggle_compact)
        header.addWidget(settings)
        header.addWidget(collapse)
        layout.addLayout(header)
        self.account = QLabel(instance.name)
        self.account.setObjectName('subtle')
        self.account.setWordWrap(True)
        layout.addWidget(self.account)
        self.connection = QLabel('正在连接')
        self.connection.setObjectName('connection')
        self.connection.setWordWrap(True)
        layout.addWidget(self.connection)
        self.summary = QLabel('等待数据')
        self.summary.setObjectName('subtle')
        layout.addWidget(self.summary)
        filters = QHBoxLayout()
        self.todo = QCheckBox('仅待办')
        self.hide_complete = QCheckBox('隐藏已完成')
        self.todo.toggled.connect(self.filter_changed)
        self.hide_complete.toggled.connect(self.filter_changed)
        filters.addWidget(self.todo)
        filters.addWidget(self.hide_complete)
        filters.addStretch()
        layout.addLayout(filters)
        self.tabs = QTabWidget()
        self.cards = {}
        for cadence, label in [('daily', '日常'), ('weekly', '周常')]:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            rows = QVBoxLayout(content)
            rows.setContentsMargins(0, 5, 3, 0)
            rows.setSpacing(6)
            for task in self.snapshot.tasks:
                if task.cadence == cadence:
                    card = TaskCard(task)
                    self.cards[task.id] = card
                    rows.addWidget(card)
            rows.addStretch(1)
            scroll.setWidget(content)
            self.tabs.addTab(scroll, label)
        layout.addWidget(self.tabs, 1)
        footer = QHBoxLayout()
        self.refresh = QPushButton('立即刷新')
        self.refresh.clicked.connect(lambda: runner.command('refresh'))
        self.pause = QPushButton('暂停')
        self.pause.setCheckable(True)
        self.pause.toggled.connect(self.set_paused)
        footer.addWidget(self.refresh)
        footer.addWidget(self.pause)
        layout.addLayout(footer)
        self.updated = QLabel('仅数据读取 · 等待首次采样')
        self.updated.setObjectName('subtle')
        layout.addWidget(self.updated)
        root.addWidget(self.expanded, 1)
        self.compact = QPushButton('猫\n›')
        self.compact.setToolTip('展开痒痒猫')
        self.compact.clicked.connect(self.toggle_compact)
        root.addWidget(self.compact, 1)
        self.compact.hide()

    def preferences(self) -> dict:
        account = self.snapshot.account
        key = account.key if account.uid or account.short_id else 'default'
        return self.manager.settings.setdefault('accounts', {}).setdefault(key, {})

    def filter_changed(self):
        self.preferences().update(todo_only=self.todo.isChecked(), hide_complete=self.hide_complete.isChecked())
        self.manager.save()
        self.render()

    def open_preferences(self):
        if self.preferences_dialog is None:
            dialog = Preferences(self)
            self.preferences_dialog = dialog
            # Tool windows need an explicit Qt transient parent on Windows.
            # Both windows belong to this GUI thread; never own the MuMu HWND.
            dialog.winId()
            dialog.windowHandle().setTransientParent(self.windowHandle())
            dialog.finished.connect(lambda result: self.preferences_closed(dialog))
            dialog.open()
        else:
            self.preferences_dialog.raise_()
            self.preferences_dialog.activateWindow()

    def preferences_closed(self, dialog):
        if self.preferences_dialog is dialog:
            self.preferences_dialog = None
            self._suspended_preferences = False
        dialog.deleteLater()

    def hideEvent(self, event):
        dialog = self.preferences_dialog
        if dialog is not None and dialog.isVisible():
            self._preferences_position = dialog.pos()
            self._suspended_preferences = True
            dialog.hide()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self._suspended_preferences and self.preferences_dialog is not None:
            self._suspended_preferences = False
            dialog = self.preferences_dialog
            dialog.move(self._preferences_position)
            # Restoring an emulator must not steal focus from its sibling or
            # another application. Keep any unsaved selections in the dialog.
            dialog.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            with windowing.preserve_thread_focus():
                dialog.show()
            dialog.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)

    def closeEvent(self, event):
        if self.preferences_dialog is not None:
            self.preferences_dialog.reject()
        super().closeEvent(event)

    def toggle_compact(self):
        self.user_collapsed = not self.user_collapsed
        self.last_placement = None
        self.follow()

    def set_paused(self, paused):
        self.runner.command('pause', paused=paused)
        self.pause.setText('继续' if paused else '暂停')
        self.refresh.setEnabled(not paused)
        self.set_connection('paused' if paused else 'connecting', '已暂停，显示上次记录' if paused else '正在恢复读取')

    def receive(self, snapshot: Snapshot):
        self.snapshot = snapshot
        self.last_received = time.monotonic()
        self.state, self.message = 'connected', snapshot.message
        account = snapshot.account
        self.account.setText(f'{account.name} · {account.server or "区服待加载"} · {account.short_id or "—"}')
        prefs = self.preferences()
        for widget, key in [(self.todo, 'todo_only'), (self.hide_complete, 'hide_complete')]:
            widget.blockSignals(True)
            widget.setChecked(bool(prefs.get(key)))
            widget.blockSignals(False)
        self.render()

    def set_connection(self, state, message):
        self.state, self.message = state, message
        self.render()

    def render(self):
        live = self.state == 'connected' and not self.pause.isChecked()
        tasks = self.snapshot.tasks
        complete = sum(t.status == Status.COMPLETE for t in tasks) if live else 0
        unknown = sum(t.status == Status.UNKNOWN for t in tasks) if live else len(tasks)
        todo = sum(t.status in (Status.INCOMPLETE, Status.PENDING, Status.IN_PROGRESS) for t in tasks) if live else 0
        self.summary.setText(f'{complete} 已完成  ·  {todo} 待办  ·  {unknown} 未确认')
        self.connection.setText(('● ' if live else '○ ') + self.message)
        self.updated.setText((f'更新 {self.snapshot.checked_at[11:19]} · {self.snapshot.duration_ms / 1000:.1f}s' if self.last_received else '等待首次采样') + ' · 只读')
        hidden = self.preferences().get('hidden_tasks', [])
        for task in tasks:
            card = self.cards.get(task.id)
            if not card:
                continue
            excluded = task.id in hidden or (live and task.status == Status.COMPLETE and (self.todo.isChecked() or self.hide_complete.isChecked()))
            card.setVisible(not excluded)
            card.update_task(task, live)

    def follow(self):
        geometry = windowing.target_geometry(self.instance.hwnd)
        if not geometry:
            self.hide()
            return
        target, work, scale = geometry
        placement = dock(target, work, width=round(300 * scale), compact=self.user_collapsed, gap=round(6 * scale))
        if self.last_placement is None or placement.collapsed != self.last_placement.collapsed:
            self.expanded.setVisible(not placement.collapsed)
            self.compact.setVisible(placement.collapsed)
        showing = not self.isVisible()
        if showing:
            self.show()
        windowing.sync_stacking(int(self.winId()), self.instance.hwnd, force=showing)
        # Qt can resize again after its first show or a DPI-change event. Reconcile
        # native bounds even when the emulator itself has not moved.
        current = windowing.window_rect(int(self.winId()))
        if current != placement.rect:
            windowing.place(int(self.winId()), placement.rect, current=current)
        if placement != self.last_placement:
            self.last_placement = placement
        if self.state == 'connected' and self.last_received and time.monotonic() - self.last_received > 30:
            self.set_connection('stale', '超过30秒未更新，显示上次记录')


class Runner(QObject):
    recovered = Signal(bool)

    def __init__(self, manager, instance: Instance):
        super().__init__(manager)
        self.manager, self.instance = manager, instance
        self.process = QProcess(self)
        self.buffer = bytearray()
        self.root_owned = False
        self.cleanup_busy = False
        self.stopping = False
        self.restart_after = 0.0
        self.panel = Panel(manager, instance, self)
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.readyReadStandardError.connect(self.read_error)
        self.process.finished.connect(self.finished)
        self.recovered.connect(self.cleanup_result)
        self.process.errorOccurred.connect(lambda err: self.panel.set_connection('offline', '读取进程未启动，正在重试'))

    def start(self):
        if self.process.state() != QProcess.ProcessState.NotRunning or self.cleanup_busy:
            return
        if self.root_owned:
            self.recover_permission()
            return
        self.stopping = False
        env = QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONUTF8', '1')
        self.process.setProcessEnvironment(env)
        arguments = [] if getattr(sys, 'frozen', False) else ['-m', 'yym']
        arguments += ['--worker', '--adb', str(self.manager.install / 'adb.exe'), '--serial', self.instance.serial, '--instance', self.instance.index]
        self.process.start(sys.executable, arguments)

    def command(self, kind, **payload):
        if self.process.state() == QProcess.ProcessState.Running:
            self.process.write((json.dumps({'type': kind, **payload}) + '\n').encode())

    def read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        while b'\n' in self.buffer:
            line, _, remaining = self.buffer.partition(b'\n')
            self.buffer = bytearray(remaining)
            try:
                value = json.loads(line)
                if value['kind'] == 'snapshot':
                    self.panel.receive(Snapshot.from_dict(value['snapshot']))
                elif value['kind'] == 'connection':
                    self.panel.set_connection(value['state'], value['message'])
                elif value['kind'] == 'lease':
                    self.root_owned = value['owned']
                elif value['kind'] == 'cleanup_error':
                    self.panel.set_connection('offline', value['message'])
            except (ValueError, TypeError, KeyError):
                pass

    def read_error(self):
        import logging
        text = bytes(self.process.readAllStandardError()).decode('utf-8', 'replace')
        if text.strip():
            logging.getLogger(__name__).warning('Worker stderr instance=%s: %s', self.instance.index, text[-3000:])

    def finished(self, code, status):
        self.read()
        self.buffer.clear()
        self.restart_after = time.monotonic() + 5
        self.panel.set_connection('offline', '连接已断开，等待重新连接')
        if self.root_owned and not self.manager.closing and not self.stopping:
            self.recover_permission()

    def recover_permission(self):
        if not self.cleanup_busy:
            self.cleanup_busy = True
            QThreadPool.globalInstance().start(PermissionCleanup(self))

    def cleanup_result(self, success):
        self.cleanup_busy = False
        if success:
            self.root_owned = False
        else:
            self.restart_after = time.monotonic() + 10
            self.panel.set_connection('offline', '等待连接恢复以还原临时读取权限')

    def stop(self):
        self.stopping = True
        self.command('stop')
        self.process.closeWriteChannel()

    def finish_cleanup(self):
        self.process.waitForFinished(10_000)
        self.read()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(3000)
        if self.root_owned:
            try:
                Adb(str(self.manager.install / 'adb.exe'), self.instance.serial).call('unroot', timeout=5)
                self.root_owned = False
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Permission cleanup failed instance=%s', self.instance.index)


class PermissionCleanup(QRunnable):
    def __init__(self, runner):
        super().__init__()
        self.runner = runner

    def run(self):
        r = self.runner
        try:
            Adb(str(r.manager.install / 'adb.exe'), r.instance.serial).call('unroot', timeout=5)
            success = True
        except Exception:
            success = False
        try:
            r.recovered.emit(success)
        except RuntimeError:
            pass  # The replaced runner was already cleaned up and deleted by the GUI.


class DiscoverySignals(QObject):
    result = Signal(object, str)


class Discovery(QRunnable):
    def __init__(self, install, signals):
        super().__init__()
        self.install, self.signals = install, signals

    def run(self):
        try:
            self.signals.result.emit(discover_instances(self.install), '')
        except Exception:
            self.signals.result.emit([], 'MuMu实例信息暂时不可用，正在重试')


class FollowScheduler(QObject):
    """A bounded set of dirty windows, flushed once per display frame outside WinEvent."""
    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self.callback = callback
        self.targets, self.pending = set(), set()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.flush)

    def set_targets(self, handles):
        self.targets = set(handles)
        self.pending.intersection_update(self.targets)

    def request(self, hwnd=0):
        if hwnd == 0:
            self.pending.update(self.targets)
        elif hwnd in self.targets:
            self.pending.add(hwnd)
        if self.pending and not self.timer.isActive():
            self.timer.start()

    def flush(self):
        pending, self.pending = self.pending, set()
        if pending:
            self.callback(pending)

    def stop(self):
        self.timer.stop()
        self.pending.clear()


class Manager(QObject):
    native_changed = Signal(object)

    def __init__(self, app: QApplication, install: Path | None):
        super().__init__()
        self.app, self.install = app, install
        self.settings = load_settings()
        self.icon = app_icon()
        app.setWindowIcon(self.icon)
        self.runners = {}
        self.busy, self.closing = False, False
        self.discovery_signals = DiscoverySignals(self)
        self.discovery_signals.result.connect(self.found)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.waiting = QWidget()
        self.waiting.setWindowTitle('痒痒猫')
        self.waiting.setObjectName('panel')
        layout = QVBoxLayout(self.waiting)
        layout.addWidget(QLabel('痒痒猫 · 等待MuMu启动'))
        self.waiting_message = QLabel('自动发现模拟器窗口，连接后在左侧显示进度。')
        self.waiting_message.setWordWrap(True)
        layout.addWidget(self.waiting_message)
        browse = QPushButton('选择MuMu安装目录')
        browse.clicked.connect(self.choose_install)
        layout.addWidget(browse)
        self.waiting.resize(340, 160)
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip('痒痒猫 · 日常与周常')
        menu = QMenu()
        show = menu.addAction('显示侧栏')
        show.triggered.connect(self.show_panels)
        menu.addAction('选择MuMu目录', self.choose_install)
        menu.addSeparator()
        menu.addAction('退出痒痒猫', app.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_panels() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()
        self.follow_scheduler = FollowScheduler(self.follow_targets, self)
        self.native_changed.connect(self.native_event)
        self.hooks = windowing.WindowHooks(self.native_changed.emit)
        self.follow_timer = QTimer(self)
        self.follow_timer.timeout.connect(self.follow)
        self.follow_timer.start(500)
        self.discovery_timer = QTimer(self)
        self.discovery_timer.timeout.connect(self.discover)
        self.discovery_timer.start(5000)
        app.aboutToQuit.connect(self.shutdown)
        self.waiting.show()
        self.discover()

    def save(self):
        save_settings(self.settings)

    def choose_install(self):
        directory = QFileDialog.getExistingDirectory(self.waiting, '选择MuMu安装目录')
        if not directory:
            return
        install = discover_install(directory)
        if not install:
            QMessageBox.information(self.waiting, '痒痒猫', '该目录内未找到MuMu CLI和ADB。')
            return
        for runner in self.runners.values():
            runner.stop()
        for runner in self.runners.values():
            runner.finish_cleanup()
            runner.panel.close()
        self.runners.clear()
        self.install = install
        self.settings['mumu_dir'] = str(install)
        self.save()
        self.discover()

    def discover(self):
        if self.busy or self.closing:
            return
        if not self.install:
            self.waiting_message.setText('请选择MuMu安装目录，或设置MUMU_HOME。')
            return
        self.busy = True
        self.pool.start(Discovery(self.install, self.discovery_signals))

    def found(self, instances, error):
        self.busy = False
        if self.closing:
            return
        if error:
            self.waiting_message.setText(error)
            for runner in self.runners.values():
                runner.panel.set_connection('offline', error)
            return
        current = {i.index: i for i in instances}
        for index in list(self.runners):
            old = self.runners[index]
            if index not in current or current[index] != old.instance:
                import logging
                logging.getLogger(__name__).info('Rebinding instance=%s old=%s new=%s', index, old.instance, current.get(index))
                old.stop()
                old.finish_cleanup()
                old.panel.close()
                old.deleteLater()
                del self.runners[index]
        for index, instance in current.items():
            if index not in self.runners:
                self.runners[index] = Runner(self, instance)
            runner = self.runners[index]
            if time.monotonic() >= runner.restart_after and not runner.panel.pause.isChecked():
                runner.start()
        handles = [r.instance.hwnd for r in self.runners.values()]
        self.hooks.set_targets(handles)
        self.follow_scheduler.set_targets(handles)
        self.waiting.setVisible(not bool(current))
        self.follow()

    def native_event(self, hwnd):
        if not self.closing:
            self.follow_scheduler.request(hwnd)

    def follow(self):
        self.follow_scheduler.request()

    def follow_targets(self, handles):
        for runner in self.runners.values():
            if runner.instance.hwnd in handles:
                runner.panel.follow()

    def show_panels(self):
        if self.runners:
            self.follow()
        else:
            self.waiting.show()
            self.waiting.raise_()

    def shutdown(self):
        if self.closing:
            return
        self.closing = True
        self.discovery_timer.stop()
        self.follow_timer.stop()
        self.follow_scheduler.stop()
        self.hooks.close()
        for runner in self.runners.values():
            runner.panel.hide()
            runner.stop()
        for runner in self.runners.values():
            runner.finish_cleanup()
        self.pool.waitForDone(16_000)
        self.tray.hide()
