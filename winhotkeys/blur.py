"""Полупрозрачный «акриловый» фон окна на Windows 10/11 — даёт эффект,
похожий на macOS vibrancy (размытие того, что под окном).

Через недокументированный, но давно и широко используемый DWM API
(SetWindowCompositionAttribute) — так делает сама оболочка Windows
(старое меню Пуск, Action Center) и множество сторонних приложений.
Best-effort: если API недоступен (старая Windows, отключённый DWM) — окно
просто останется без размытия, без падения.
"""
from __future__ import annotations

import ctypes

ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
WCA_ACCENT_POLICY = 19

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


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


def get_window_hwnd(tk_root) -> int:
    """HWND настоящего верхнеуровневого окна для объекта tkinter/CTk."""
    root_id = tk_root.winfo_id()
    parent = ctypes.windll.user32.GetParent(root_id)
    return parent or root_id


def enable_window_blur(hwnd: int, tint: tuple[int, int, int] = (24, 24, 27), opacity: int = 190) -> bool:
    """Включает акриловое размытие для окна hwnd. Возвращает True при успехе,
    False — если API недоступен или вызов не удался (тогда просто не будет
    размытия, работоспособность окна это не затрагивает)."""
    try:
        set_attr = ctypes.windll.user32.SetWindowCompositionAttribute
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


def enable_rounded_corners(hwnd: int) -> bool:
    """Включает системное скругление углов окна через DWM (Windows 11).

    В отличие от скруглённого фона внутри виджета, это скругляет саму форму
    окна — размытие фона (см. enable_window_blur) корректно обрезается по
    скруглённой границе, без квадратных уголков поверх него. Best-effort:
    на Windows 10 (или при отключённом DWM) атрибут не поддерживается —
    окно остаётся с прямыми углами, без падения."""
    try:
        dwmapi = ctypes.windll.dwmapi
    except OSError:
        return False

    preference = ctypes.c_int(DWMWCP_ROUND)
    try:
        result = dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(preference),
            ctypes.sizeof(preference),
        )
        return result == 0
    except OSError:
        return False
