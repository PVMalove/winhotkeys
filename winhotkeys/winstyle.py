"""Акриловое размытие фона окна панели (см. panel.py) по HWND — то, чего
нет "из коробки" в Qt.

Через недокументированный, но давно и широко используемый DWM API
(SetWindowCompositionAttribute) — так делает сама оболочка Windows (старое
меню Пуск, Action Center) и множество сторонних приложений. Best-effort:
если API недоступен (старая Windows, отключённый DWM) — окно просто
останется без размытия, без падения.

Позиционирование/скрытие из панели задач у панели теперь отдаёт сам Qt
(move()/resize(), флаг Qt.Tool) — раньше здесь же жили SetWindowPos/
SetWindowRgn/GWL_EXSTYLE-обвязки для pywebview, но тот стек полностью
заменён на PySide6 (см. docs/adr/0004-panel-renders-via-qt.md), и вместе
с ним ушла нужда в этих функциях.
"""
from __future__ import annotations

import ctypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
WCA_ACCENT_POLICY = 19


class _AccentPolicy(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int),
    ]


class _WindowCompositionAttributeData(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.POINTER(_AccentPolicy)),
        ("SizeOfData", ctypes.c_size_t),
    ]


def enable_window_blur(hwnd: int, tint: tuple[int, int, int] = (28, 30, 40), opacity: int = 160) -> bool:
    """Включает акриловое размытие для окна hwnd. Возвращает True при
    успехе, False — если API недоступен или вызов не удался (тогда просто
    не будет размытия, работоспособность окна это не затрагивает)."""
    try:
        set_attr = user32.SetWindowCompositionAttribute
    except (AttributeError, OSError):
        return False

    r, g, b = tint
    accent = _AccentPolicy()
    accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
    accent.AccentFlags = 0
    accent.GradientColor = (max(0, min(opacity, 255)) << 24) | (b << 16) | (g << 8) | r
    accent.AnimationId = 0

    data = _WindowCompositionAttributeData()
    data.Attribute = WCA_ACCENT_POLICY
    data.SizeOfData = ctypes.sizeof(accent)
    data.Data = ctypes.pointer(accent)

    try:
        return bool(set_attr(hwnd, ctypes.byref(data)))
    except OSError:
        return False
