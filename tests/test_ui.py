import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from yym.models import Instance, Status
from yym.rules import evaluate
from yym.ui import Panel, app_icon


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


class Manager:
    settings = {}
    def __init__(self):
        self.settings = {}
        self.icon = app_icon()
    def save(self):
        pass


class Runner:
    def command(self, *args, **kwargs):
        pass


def test_offline_never_displays_previous_completed_as_current(app, monkeypatch):
    panel = Panel(Manager(), Instance('0', 'test', 0, 0, 'test'), Runner())
    snap = evaluate({'daily_current': True, 'pet_bonus': True, 'account': {'uid': 'test'}})
    panel.receive(snap)
    assert panel.cards['pet_bonus'].badge.text() == '已完成'
    panel.set_connection('offline', '连接已断开')
    assert panel.cards['pet_bonus'].badge.text() == '未确认'
    assert '上次记录' in panel.cards['pet_bonus'].detail.text()
    panel.close()


def test_task_visibility_and_account_switch_are_isolated(app, monkeypatch):
    panel = Panel(Manager(), Instance('0', 'test', 0, 0, 'test'), Runner())
    panel.receive(evaluate({'account': {'uid': 'a'}, 'daily_current': True, 'pet_bonus': True}))
    panel.hide_complete.setChecked(True)
    assert panel.cards['pet_bonus'].isHidden()
    panel.receive(evaluate({'account': {'uid': 'b'}, 'daily_current': True, 'pet_bonus': True}))
    assert not panel.hide_complete.isChecked()
    assert not panel.cards['pet_bonus'].isHidden()
    panel.close()


def test_preferences_are_per_window_nonblocking_and_reused(app):
    panels = [Panel(Manager(), Instance(str(i), 'test', 0, 0, 'test'), Runner()) for i in range(2)]
    try:
        for panel in panels:
            panel.show()
        panels[0].open_preferences()
        first = panels[0].preferences_dialog
        assert first is not None and first.isVisible()
        assert first.windowModality() == Qt.WindowModality.WindowModal
        panels[0].open_preferences()
        assert panels[0].preferences_dialog is first
        panels[1].open_preferences()
        assert panels[1].preferences_dialog is not first
        assert first.isVisible() and panels[1].preferences_dialog.isVisible()
    finally:
        for panel in panels:
            panel.close()


def test_hiding_one_panel_suspends_its_dialog_and_preserves_unsaved_choices(app):
    panels = [Panel(Manager(), Instance(str(i), 'test', 0, 0, 'test'), Runner()) for i in range(2)]
    try:
        for panel in panels:
            panel.show()
            panel.open_preferences()
        first, second = [p.preferences_dialog for p in panels]
        first.items.item(0).setCheckState(Qt.CheckState.Unchecked)
        panels[0].hide()
        assert not first.isVisible() and second.isVisible() and panels[1].isVisible()
        panels[0].show()
        assert first.isVisible() and first.items.item(0).checkState() == Qt.CheckState.Unchecked
        first.reject()
        assert panels[0].preferences_dialog is None
        panels[0].hide()
        panels[0].show()
        assert panels[0].preferences_dialog is None
    finally:
        for panel in panels:
            panel.close()
        assert all(p.preferences_dialog is None for p in panels)
