"""Чистая логика переключения между окнами одной программы — без
зависимости от WinAPI, поэтому легко покрывается юнит-тестами."""
from __future__ import annotations


def pick_next_action(window_count: int, current_index: int | None) -> tuple[str, int]:
    """Следующее действие для повторного нажатия Alt+N.

    Если ни одно окно программы сейчас не активно — фокусируем первое окно
    (как и раньше). Если активно последнее окно в списке — вместо
    зацикливания на первое сворачиваем его: при одном окне повторное
    нажатие превращается в переключатель фокус/свёрнуто, а при нескольких —
    сначала пролистываем все окна по очереди, и только на последнем
    сворачиваем.

    Возвращает ("focus", index) или ("minimize", index).
    """
    if window_count <= 0:
        raise ValueError("window_count должен быть положительным")
    if current_index is None or not (0 <= current_index < window_count):
        return ("focus", 0)
    if current_index == window_count - 1:
        return ("minimize", current_index)
    return ("focus", current_index + 1)


def find_index(windows: list, active_window) -> int | None:
    """Индекс активного окна в списке окон программы, либо None."""
    if active_window is None:
        return None
    try:
        return windows.index(active_window)
    except ValueError:
        return None
