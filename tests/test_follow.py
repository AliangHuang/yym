import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from yym.geometry import Rect
from yym.ui import FollowScheduler
from yym import windowing


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_event_burst_is_coalesced_and_never_runs_follow_inside_hook(app):
    calls = []
    scheduler = FollowScheduler(calls.append)
    scheduler.set_targets([101, 202])
    for _ in range(2000):
        scheduler.request(101)
    scheduler.request(202)
    scheduler.request(999)
    assert calls == [] and scheduler.pending == {101, 202}
    loop = QEventLoop()
    QTimer.singleShot(40, loop.quit)
    loop.exec()
    assert calls == [{101, 202}]
    scheduler.stop()


def test_replaced_instances_remove_pending_events_and_shutdown_cancels(app):
    calls = []
    scheduler = FollowScheduler(calls.append)
    scheduler.set_targets([101])
    scheduler.request(101)
    scheduler.set_targets([202])
    scheduler.flush()
    assert calls == []
    scheduler.request()
    scheduler.stop()
    assert not scheduler.timer.isActive() and not scheduler.pending


def test_native_hook_ignores_unrelated_and_accessibility_children():
    hook = object.__new__(windowing.WindowHooks)
    hook.targets = frozenset({101})
    calls = []
    hook.notify = calls.append
    hook.on_event(None, 0x800B, 101, -4, 0, 0, 0)
    hook.on_event(None, 0x800B, 101, 0, 1, 0, 0)
    hook.on_event(None, 0x800B, 999, 0, 0, 0, 0)
    assert calls == []
    hook.on_event(None, 0x800B, 101, 0, 0, 0, 0)
    hook.on_event(None, 3, 999, 0, 0, 0, 0)
    assert calls == [101, 0]


def test_position_only_move_sets_nosize_and_identical_rect_is_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(windowing.user, 'SetWindowPos', lambda *args: calls.append(args))
    original, moved = Rect(100, 200, 300, 600), Rect(110, 220, 300, 600)
    windowing.place(101, moved, original)
    assert calls[0][-1] & 0x0001
    assert calls[0][-1] & 0x0010
    windowing.place(101, moved, moved)
    assert len(calls) == 1
    windowing.place(101, Rect(110, 220, 300, 700), moved)
    assert not calls[-1][-1] & 0x0001


def test_foreground_stacking_only_changes_our_window_without_activation(monkeypatch):
    calls = []
    monkeypatch.setattr(windowing.user, 'GetForegroundWindow', lambda: 101)
    monkeypatch.setattr(windowing.user, 'GetAncestor', lambda *args: 101)
    monkeypatch.setattr(windowing.user, 'GetWindowLongPtrW', lambda *args: 0)
    monkeypatch.setattr(windowing.user, 'SetWindowPos', lambda *args: calls.append(args))
    monkeypatch.setattr(windowing, 'process_id', lambda h: 99999)
    windowing.sync_stacking(202, 101)
    assert len(calls) == 1 and calls[0][0] == 202
    assert calls[0][-1] & 0x0010
    assert calls[0][-1] & 0x0001 and calls[0][-1] & 0x0002


def test_background_demotes_sidebar_and_leaves_emulator_untouched(monkeypatch):
    calls = []
    monkeypatch.setattr(windowing.user, 'GetForegroundWindow', lambda: 303)
    monkeypatch.setattr(windowing.user, 'GetAncestor', lambda *args: 303)
    monkeypatch.setattr(windowing.user, 'GetWindowLongPtrW', lambda hwnd, kind: 8 if hwnd == 202 else 0)
    monkeypatch.setattr(windowing.user, 'GetWindow', lambda *args: 0)
    monkeypatch.setattr(windowing.user, 'SetWindowPos', lambda *args: calls.append(args))
    monkeypatch.setattr(windowing, 'process_id', lambda h: 99999)
    windowing.sync_stacking(202, 101)
    assert len(calls) == 2 and all(c[0] == 202 for c in calls)
    assert calls[-1][1] == 101


def test_geometry_hooks_are_scoped_to_target_process_and_skip_own_events(monkeypatch):
    calls = []
    hook = object.__new__(windowing.WindowHooks)
    hook.targets, hook.target_hooks, hook.callback = frozenset(), [], None
    monkeypatch.setattr(windowing, 'process_id', lambda h: 900)
    monkeypatch.setattr(windowing.user, 'SetWinEventHook', lambda *args: calls.append(args) or len(calls))
    monkeypatch.setattr(windowing.user, 'UnhookWinEvent', lambda h: None)
    hook.set_targets([101, 202])
    assert len(calls) == 3
    assert all(c[-3] == 900 and c[-1] & 2 for c in calls)
    hook.set_targets([101, 202])
    assert len(calls) == 3


def test_activating_one_sidebar_never_promotes_its_sibling(monkeypatch):
    calls = []
    monkeypatch.setattr(windowing.user, 'GetForegroundWindow', lambda: 202)
    monkeypatch.setattr(windowing.user, 'GetAncestor', lambda *args: 202)
    monkeypatch.setattr(windowing.user, 'GetWindow', lambda hwnd, kind: 404 if (hwnd, kind) == (303, 3) else 0)
    monkeypatch.setattr(windowing.user, 'GetWindowLongPtrW', lambda *args: 0)
    monkeypatch.setattr(windowing.user, 'SetWindowPos', lambda *args: calls.append(args))
    monkeypatch.setattr(windowing, 'process_id', lambda h: os.getpid())
    windowing.sync_stacking(303, 404)
    assert calls == []  # Same process is insufficient: this is the background sidebar.


def test_dialog_activation_only_promotes_its_own_sidebar(monkeypatch):
    calls = []
    monkeypatch.setattr(windowing.user, 'GetForegroundWindow', lambda: 303)
    monkeypatch.setattr(windowing.user, 'GetAncestor', lambda *args: 303)
    monkeypatch.setattr(windowing.user, 'GetWindow', lambda hwnd, kind: {(303, 4): 202, (404, 3): 505}.get((hwnd, kind), 0))
    monkeypatch.setattr(windowing.user, 'GetWindowLongPtrW', lambda *args: 0)
    monkeypatch.setattr(windowing.user, 'SetWindowPos', lambda *args: calls.append(args))
    windowing.sync_stacking(202, 101)
    windowing.sync_stacking(404, 505)
    assert len(calls) == 1 and calls[0][0] == 202


def test_foreground_owner_cycles_are_bounded(monkeypatch):
    monkeypatch.setattr(windowing.user, 'GetAncestor', lambda *args: 303)
    monkeypatch.setattr(windowing.user, 'GetWindow', lambda hwnd, kind: {303: 404, 404: 303}[hwnd])
    assert not windowing.belongs_to_panel(303, 202, 101)


def test_background_topmost_target_does_not_cause_repeated_restacking(monkeypatch):
    calls = []
    monkeypatch.setattr(windowing, 'belongs_to_panel', lambda *args: False)
    monkeypatch.setattr(windowing.user, 'GetForegroundWindow', lambda: 999)
    monkeypatch.setattr(windowing.user, 'GetWindowLongPtrW', lambda *args: 8)
    monkeypatch.setattr(windowing.user, 'GetWindow', lambda hwnd, kind: 101)
    monkeypatch.setattr(windowing.user, 'SetWindowPos', lambda *args: calls.append(args))
    for _ in range(20):
        windowing.sync_stacking(202, 101)
    assert calls == []


def test_inactive_sidebar_tracks_changed_target_z_order_without_activation(monkeypatch):
    calls = []
    monkeypatch.setattr(windowing, 'belongs_to_panel', lambda *args: False)
    monkeypatch.setattr(windowing.user, 'GetForegroundWindow', lambda: 999)
    monkeypatch.setattr(windowing.user, 'GetWindowLongPtrW', lambda *args: 0)
    monkeypatch.setattr(windowing.user, 'GetWindow', lambda hwnd, kind: 303)
    monkeypatch.setattr(windowing.user, 'SetWindowPos', lambda *args: calls.append(args))
    windowing.sync_stacking(202, 101)
    assert len(calls) == 1 and calls[0][0:2] == (202, 101)
    assert calls[0][-1] & 0x0010


def test_modal_restore_preserves_native_thread_focus_without_foreground_activation(monkeypatch):
    state, calls = {'active': 101, 'focus': 102, 'foreground': 999}, []
    monkeypatch.setattr(windowing.user, 'GetActiveWindow', lambda: state['active'])
    monkeypatch.setattr(windowing.user, 'GetFocus', lambda: state['focus'])
    monkeypatch.setattr(windowing.user, 'GetForegroundWindow', lambda: state['foreground'])
    monkeypatch.setattr(windowing.user, 'IsWindow', lambda hwnd: True)
    monkeypatch.setattr(windowing.user, 'SetActiveWindow', lambda hwnd: calls.append(('active', hwnd)))
    monkeypatch.setattr(windowing.user, 'SetFocus', lambda hwnd: calls.append(('focus', hwnd)))
    with windowing.preserve_thread_focus():
        state.update(active=201, focus=202)
    assert calls == [('active', 101), ('focus', 102)]
    calls.clear()
    with windowing.preserve_thread_focus():
        state.update(active=301, focus=302, foreground=888)
    assert calls == []  # A concurrent foreground change must take precedence.
