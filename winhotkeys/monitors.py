"""Монитор, на котором сейчас находится курсор мыши — чтобы оверлей
открывался на «активном» экране, а не всегда на одном и том же (актуально
для мультимониторных систем)."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

MONITOR_DEFAULTTONEAREST = 2

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

user32 = ctypes.WinDLL("user32", use_last_error=True)


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
    ]


user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL

user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HMONITOR

user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int


def get_work_area_at_cursor() -> tuple[int, int, int, int]:
    """(left, top, right, bottom) рабочей области (без панели задач) монитора
    под курсором, в физических пикселях. Best-effort: при любой ошибке
    WinAPI — откат на весь виртуальный экран (все мониторы вместе)."""
    point = wintypes.POINT()
    if user32.GetCursorPos(ctypes.byref(point)):
        monitor = user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
        if monitor:
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.rcWork
                return r.left, r.top, r.right, r.bottom

    left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return left, top, left + width, top + height
