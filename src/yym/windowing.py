"""Physical-pixel Windows geometry, no screenshots or rendered-content inspection."""
from __future__ import annotations

import ctypes
from contextlib import contextmanager
from ctypes import wintypes as w
import os

from yym.geometry import Rect

if os.name == 'nt':
    user = ctypes.WinDLL('user32', use_last_error=True)
    dwm = ctypes.WinDLL('dwmapi', use_last_error=True)
    user.IsWindow.argtypes = [w.HWND]
    user.IsIconic.argtypes = [w.HWND]
    user.IsWindowVisible.argtypes = [w.HWND]
    user.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    user.GetWindow.argtypes = [w.HWND, w.UINT]
    user.GetWindow.restype = w.HWND
    user.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
    user.MonitorFromWindow.restype = w.HMONITOR
    user.GetMonitorInfoW.argtypes = [w.HMONITOR, ctypes.c_void_p]
    user.GetDpiForWindow.argtypes = [w.HWND]
    user.GetDpiForWindow.restype = w.UINT
    user.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT]
    user.SetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user.GetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int]
    user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user.GetForegroundWindow.restype = w.HWND
    user.GetActiveWindow.restype = w.HWND
    user.GetFocus.restype = w.HWND
    user.SetActiveWindow.argtypes, user.SetActiveWindow.restype = [w.HWND], w.HWND
    user.SetFocus.argtypes, user.SetFocus.restype = [w.HWND], w.HWND
    user.GetAncestor.argtypes = [w.HWND, w.UINT]
    user.GetAncestor.restype = w.HWND
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user.GetWindowThreadProcessId.restype = w.DWORD
    dwm.DwmGetWindowAttribute.argtypes = [w.HWND, w.DWORD, ctypes.c_void_p, w.DWORD]


def enable_dpi() -> None:
    if os.name == 'nt':
        user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))


def target_geometry(hwnd: int) -> tuple[Rect, Rect, float] | None:
    if os.name != 'nt' or not user.IsWindow(hwnd) or user.IsIconic(hwnd) or not user.IsWindowVisible(hwnd):
        return None
    rect = w.RECT()
    if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)):
        if not user.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
    class MonitorInfo(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('monitor', w.RECT), ('work', w.RECT), ('flags', w.DWORD)]
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    if not user.GetMonitorInfoW(user.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):
        return None
    work = info.work
    return (Rect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
            Rect(work.left, work.top, work.right - work.left, work.bottom - work.top),
            (user.GetDpiForWindow(hwnd) or 96) / 96)


def process_id(hwnd: int) -> int:
    pid = w.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


@contextmanager
def preserve_thread_focus():
    """Qt modal restores can change thread focus even with SHOWWITHOUTACTIVATING."""
    if os.name != 'nt':
        yield
        return
    active, focus = user.GetActiveWindow(), user.GetFocus()
    foreground = user.GetForegroundWindow()
    try:
        yield
    finally:
        # Only restore this thread's input state, and respect a foreground change
        # made by the user. Never activate another application or attach queues.
        if user.GetForegroundWindow() == foreground:
            if user.GetActiveWindow() != active and (not active or user.IsWindow(active)):
                user.SetActiveWindow(active)
            if user.GetFocus() != focus and (not focus or user.IsWindow(focus)):
                user.SetFocus(focus)


def sync_stacking(panel: int, target: int, force: bool = False) -> None:
    """Keep independent input queues; never assign the emulator as GWLP_HWNDPARENT."""
    if os.name != 'nt':
        return
    foreground = user.GetForegroundWindow()
    active = belongs_to_panel(foreground, panel, target)
    topmost = bool(user.GetWindowLongPtrW(panel, -20) & 8)
    flags = 0x0010 | 0x0001 | 0x0002 | 0x0200
    if active and not topmost:
        user.SetWindowPos(panel, w.HWND(-1), 0, 0, 0, 0, flags)
    elif not active:
        target_topmost = bool(user.GetWindowLongPtrW(target, -20) & 8)
        # Inserting after a topmost target also makes the sidebar topmost. Match
        # that band instead of demoting/promoting on every follow frame.
        if topmost and not target_topmost:
            user.SetWindowPos(panel, w.HWND(-2), 0, 0, 0, 0, flags)
        if force or topmost != target_topmost or int(user.GetWindow(panel, 3) or 0) != target:
            user.SetWindowPos(panel, target, 0, 0, 0, 0, flags)


def belongs_to_panel(foreground: int, panel: int, target: int) -> bool:
    """Match this instance's windows, never every sidebar sharing our process."""
    root = int(user.GetAncestor(foreground, 2) or 0) if foreground else 0
    seen = set()
    while root and root not in seen and len(seen) < 32:
        if root in (panel, target):
            return True
        seen.add(root)
        # Read existing owner chains for dialogs/popups; create no cross-process owners.
        root = int(user.GetWindow(root, 4) or 0)
    return False


def window_rect(hwnd: int) -> Rect | None:
    if os.name != 'nt':
        return None
    rect = w.RECT()
    if user.GetWindowRect(hwnd, ctypes.byref(rect)):
        return Rect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    return None


def place(hwnd: int, rect: Rect, current: Rect | None = None) -> None:
    if os.name == 'nt':
        current = current or window_rect(hwnd)
        if current == rect:
            return
        flags = 0x0010 | 0x0004 | 0x0200
        if current and (current.width, current.height) == (rect.width, rect.height):
            flags |= 0x0001  # SWP_NOSIZE: moving must not resize/reflow all cards.
        if current and (current.x, current.y) == (rect.x, rect.y):
            flags |= 0x0002
        user.SetWindowPos(hwnd, None, rect.x, rect.y, rect.width, rect.height, flags)


class WindowHooks:
    def __init__(self, callback):
        self.hooks, self.target_hooks = [], []
        self.targets = frozenset()
        self.notify = callback
        if os.name != 'nt':
            return
        prototype = ctypes.WINFUNCTYPE(None, w.HANDLE, w.DWORD, w.HWND, w.LONG, w.LONG, w.DWORD, w.DWORD)
        self.callback = prototype(self.on_event)
        user.SetWinEventHook.argtypes = [w.DWORD, w.DWORD, w.HMODULE, prototype, w.DWORD, w.DWORD, w.DWORD]
        user.SetWinEventHook.restype = w.HANDLE
        user.UnhookWinEvent.argtypes = [w.HANDLE]
        hook = user.SetWinEventHook(3, 3, None, self.callback, 0, 0, 0)
        if hook:
            self.hooks.append(hook)

    def set_targets(self, handles) -> None:
        targets = frozenset(handles)
        if targets == self.targets:
            return
        self.targets = targets
        if os.name != 'nt':
            return
        for hook in self.target_hooks:
            user.UnhookWinEvent(hook)
        self.target_hooks.clear()
        for pid in {process_id(hwnd) for hwnd in targets} - {0}:
            for low, high in [(0x800B, 0x800B), (0x0016, 0x0017), (0x8002, 0x8003)]:
                hook = user.SetWinEventHook(low, high, None, self.callback, pid, 0, 2)
                if hook:
                    self.target_hooks.append(hook)

    def on_event(self, hook, event, hwnd, obj, child, thread, when):
        if event == 3:
            self.notify(0)
        elif hwnd in self.targets and obj == 0 and child == 0:
            # Only target window events; ignore accessibility children and our own paints.
            self.notify(int(hwnd))

    def close(self):
        for hook in self.hooks + self.target_hooks:
            user.UnhookWinEvent(hook)
        self.hooks.clear()
        self.target_hooks.clear()
        self.targets = frozenset()
