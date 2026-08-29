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


EDGE_THRESHOLD_PX = 6
HOVER_DWELL_S = 0.25


def is_cursor_at_edge(
    cursor_x: int,
    monitor_left: int,
    monitor_right: int,
    side: str,
    threshold_px: int = EDGE_THRESHOLD_PX,
) -> bool:
    """Находится ли курсор в узкой зоне у настроенного края монитора —
    общая проверка для триггеров "edge-slide" и "hover" (разница между
    ними — в EdgeDwellTracker ниже, не здесь)."""
    if side == "right":
        return cursor_x >= monitor_right - threshold_px
    if side == "left":
        return cursor_x <= monitor_left + threshold_px
    raise ValueError(f"неизвестная сторона панели: {side}")


class EdgeDwellTracker:
    """Для триггера "hover": в отличие от "edge-slide" (срабатывает
    мгновенно при касании края), панель должна показаться только после
    того, как курсор непрерывно провёл в зоне края не менее dwell_seconds.
    Время инжектируется (не time.monotonic() внутри) — тестируется без
    реальных задержек."""

    def __init__(self, dwell_seconds: float = HOVER_DWELL_S):
        self._dwell_seconds = dwell_seconds
        self._entered_at: float | None = None

    def update(self, in_zone: bool, now: float) -> bool:
        if not in_zone:
            self._entered_at = None
            return False
        if self._entered_at is None:
            self._entered_at = now
        return now - self._entered_at >= self._dwell_seconds
