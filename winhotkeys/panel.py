"""Резидентная боковая панель быстрого доступа — заменяет собой прежнее
модальное меню Alt+0 (см. ADR docs/adr/0001-panel-replaces-modal-overlay.md).
Один процесс, запускается один раз при `start` (daemon.start_panel_background)
и живёт до `stop`.

Рендерится через PySide6 (нативные Qt-виджеты): прозрачные/скруглённые
окна у Qt (WA_TranslucentBackground + QSS)

Триггер "hotkey" слушается в фоновом потоке тем же паттерном, что и
daemon.py (register_hotkey/get_message), и сигнализирует Qt-потоку через
Qt Signal — Qt-сигналы потокобезопасны между потоками "из коробки"
(становятся QueuedConnection автоматически), отдельная очередь не нужна.

Курсор/мониторы читаются через QCursor/QScreen, а не через сырой WinAPI
(monitors.py) — у Qt (в отличие от pywebview) эти координаты уже
согласованы между собой и сами учитывают разный DPI-масштаб на разных
мониторах, без ручного пересчёта.
"""

from __future__ import annotations

import io
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSequentialAnimationGroup,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPixmap, QPen
from PySide6.QtNetwork import QHostAddress, QUdpSocket
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import daemon, icons, win32api
from .core import EdgeDwellTracker, is_cursor_at_edge

PANEL_HOTKEY_ID = 0
PANEL_HOTKEY_VK = 0x30  # VK_0

CHIP_GAP = 50  # зазор между капсулой и всплывающим чипом подписи, px
TICK_MS = 40

# None ("Никогда") означает "никогда не скрывать автоматически".
HIDE_DELAY_MS: dict[int | None, int | None] = {1: 1000, 3: 3000, 6: 6000, None: None}

PALETTE = [
    "#0a84ff",
    "#ff9f0a",
    "#30d158",
    "#ffd60a",
    "#bf5af2",
    "#ff375f",
    "#64d2ff",
    "#a2845e",
]

ICON_PX = 40
ICON_HOVER_PX = 46  # размер иконки при наведении (dock-эффект увеличения)
ICON_RADIUS = 12  # скругление иконок-квадратиков (squircle), как в макете
ICON_HOVER_RADIUS = round(ICON_RADIUS * ICON_HOVER_PX / ICON_PX)
ICON_ANIM_MS = 140
PULSE_MS = 500  # общая длительность анимации пульсации
PANEL_WIDTH = 76
HAIRLINE = "rgba(255, 255, 255, 23)"

TEXT_1 = "#F3F4F8"
ACCENT_STRONG = "#9BA6FF"

CHIP_QSS = f"""
QLabel#chipName {{ color: {TEXT_1}; font-weight: 600; font-size: 13px; }}
QLabel#chipKey {{
  color: {ACCENT_STRONG};
  font-family: Consolas, "Cascadia Code";
  font-weight: 600;
  font-size: 10px;
  background: rgba(124, 140, 255, 36);
  border: 1px solid rgba(124, 140, 255, 77);
  border-radius: 6px;
  padding: 3px 7px;
}}
"""


def _placeholder_color(name: str) -> str:
    return PALETTE[sum(map(ord, name)) % len(PALETTE)]


def _pil_to_pixmap(image) -> QPixmap:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    pixmap = QPixmap()
    pixmap.loadFromData(buf.getvalue(), "PNG")
    return pixmap


def _rounded_pixmap(source: QPixmap, size: int, radius: int) -> QPixmap:
    result = QPixmap(size, size)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, size, size, source)
    painter.end()
    return result


def _glyph_pixmap(
        glyph: str, background: QColor, size: int, radius: int, font_px: int | None = None
) -> QPixmap:
    result = QPixmap(size, size)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, radius, radius)
    painter.setClipPath(path)
    painter.fillRect(0, 0, size, size, background)
    painter.setPen(Qt.white)
    font = QFont()
    font.setPixelSize(font_px or int(size * 0.45))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRect(0, 0, size, size), Qt.AlignCenter, glyph)
    painter.end()
    return result


def _icon_pixmap(bind: dict[str, Any], source_path: str | None) -> QPixmap:
    image = icons.get_icon_image(bind, source_path=source_path) if source_path else None
    if image is not None:
        raw = _pil_to_pixmap(
            image.convert("RGBA").resize((ICON_HOVER_PX, ICON_HOVER_PX))
        )
        return _rounded_pixmap(raw, ICON_HOVER_PX, ICON_HOVER_RADIUS)
    letter = (bind["name"][:1] or "?").upper()
    return _glyph_pixmap(
        letter,
        QColor(_placeholder_color(bind["name"])),
        ICON_HOVER_PX,
        ICON_HOVER_RADIUS,
    )


class LabelChip(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("chip")
        self.setStyleSheet(CHIP_QSS)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 7, 14, 7)
        layout.setSpacing(8)
        self._name = QLabel(self)
        self._name.setObjectName("chipName")
        self._key = QLabel(self)
        self._key.setObjectName("chipKey")
        layout.addWidget(self._name)
        layout.addWidget(self._key)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setBrush(QColor(28, 30, 40, 210))
        pen = QPen(QColor(255, 255, 255, 26))
        pen.setWidth(1)
        painter.setPen(pen)

        radius = 10
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.drawRoundedRect(rect, radius, radius)

    def show_for(
            self, name: str, hotkey: str, row_global_pos: QPoint, row_size, side: str
    ) -> None:
        self._name.setText(name)
        self._key.setText(hotkey)
        self._key.setVisible(bool(hotkey))
        self.adjustSize()

        y = row_global_pos.y() + (row_size.height() - self.height()) // 2
        if side == "right":
            x = row_global_pos.x() - CHIP_GAP - self.width()
        else:
            x = row_global_pos.x() + row_size.width() + CHIP_GAP
        self.move(x, y)
        self.show()


class Row(QWidget):
    def __init__(
            self,
            number: str,
            bind: dict[str, Any],
            pixmap: QPixmap,
            on_select,
            on_enter,
            on_leave,
            parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.number = number
        self.bind = bind
        self._on_select = on_select
        self._on_enter = on_enter
        self._on_leave = on_leave
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(ICON_HOVER_PX, ICON_HOVER_PX)
        self.setMouseTracking(True)

        self._rest_rect = QRect(
            (ICON_HOVER_PX - ICON_PX) // 2,
            (ICON_HOVER_PX - ICON_PX) // 2,
            ICON_PX,
            ICON_PX,
            )
        self._hover_rect = QRect(0, 0, ICON_HOVER_PX, ICON_HOVER_PX)

        self.icon_label = QLabel(self)
        self.icon_label.setScaledContents(True)
        self.icon_label.setGeometry(self._rest_rect)
        self.icon_label.setPixmap(pixmap)

        self._icon_anim = QPropertyAnimation(self.icon_label, b"geometry", self)
        self._icon_anim.setDuration(ICON_ANIM_MS)
        self._icon_anim.setEasingCurve(QEasingCurve.OutCubic)

    def _animate_icon_to(self, target: QRect) -> None:
        self._icon_anim.stop()
        self._icon_anim.setStartValue(self.icon_label.geometry())
        self._icon_anim.setEndValue(target)
        self._icon_anim.start()

    def enterEvent(self, event) -> None:
        self._animate_icon_to(self._hover_rect)
        self._on_enter(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_icon_to(self._rest_rect)
        self._on_leave(self)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._on_select(self)
        super().mousePressEvent(event)

    def pulse(self, duration_ms: int = PULSE_MS) -> None:
        self._icon_anim.stop()

        loops = 3
        loop_duration = duration_ms // loops
        half = loop_duration // 2

        grow = QPropertyAnimation(self.icon_label, b"geometry", self)
        grow.setDuration(half)
        grow.setStartValue(self._rest_rect)
        grow.setEndValue(self._hover_rect)
        grow.setEasingCurve(QEasingCurve.InOutQuad)

        shrink = QPropertyAnimation(self.icon_label, b"geometry", self)
        shrink.setDuration(loop_duration - half)
        shrink.setStartValue(self._hover_rect)
        shrink.setEndValue(self._rest_rect)
        shrink.setEasingCurve(QEasingCurve.InOutQuad)

        self._pulse_group = QSequentialAnimationGroup(self)
        self._pulse_group.addAnimation(grow)
        self._pulse_group.addAnimation(shrink)
        self._pulse_group.setLoopCount(loops)

        self._pulse_group.finished.connect(self.parent().hide_panel)
        self._pulse_group.start()


SETTINGS_GLYPH = "⚙"  # ⚙


class Panel(QWidget):
    _hotkey_signal = Signal()

    def __init__(self, config: dict[str, Any], config_path: Path):
        super().__init__(
            None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("panel")
        self.setFixedWidth(PANEL_WIDTH)
        self.setMouseTracking(True)

        self.binds = config["binds"]
        self.config_path = config_path
        settings = config["panel"]
        self.trigger: str = settings["trigger"]
        self.side: str = settings["side"]
        self.hide_delay_ms = HIDE_DELAY_MS[settings["hide_delay"]]
        self.icon_spacing: int = settings.get("icon_spacing", 6)
        self.edge_offset: int = settings.get("edge_offset", 24)

        self._visible = False
        self._is_hiding = False

        # НОВЫЙ ФЛАГ для предотвращения преждевременного закрытия
        self._mouse_entered = False

        self._dwell = EdgeDwellTracker()
        self._clear_of_edge = True

        self._chip = LabelChip()
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_panel)

        self._pos_anim = QPropertyAnimation(self, b"pos", self)
        self._pos_anim.setDuration(250)
        self._pos_anim.finished.connect(self._on_pos_anim_finished)

        self._build_rows()

        self._hotkey_signal.connect(self.show_panel)
        if self.trigger == "hotkey":
            self._start_hotkey_thread()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._tick)
        self._poll_timer.start(TICK_MS)

        self._udp = QUdpSocket(self)
        self._udp.bind(QHostAddress.LocalHost, daemon.PANEL_NOTIFY_PORT)
        self._udp.readyRead.connect(self._on_udp_ready)

    def _on_pos_anim_finished(self) -> None:
        if self._is_hiding:
            self.hide()
            self._visible = False
            self._is_hiding = False

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setBrush(QColor(28, 30, 40, 100))
        pen = QPen(QColor(255, 255, 255, 26))
        pen.setWidth(1)
        painter.setPen(pen)

        radius = PANEL_WIDTH // 2
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.drawRoundedRect(rect, radius, radius)

    # ---- UI --------------------------------------------------------------

    def _build_rows(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(self.icon_spacing)

        items = sorted(self.binds.items(), key=lambda kv: kv[0])
        icon_sources = icons.resolve_icon_sources([bind for _, bind in items])
        for number, bind in items:
            pixmap = _icon_pixmap(bind, icon_sources.get(id(bind)))
            row = Row(
                number,
                bind,
                pixmap,
                self._select,
                self._on_row_enter,
                self._on_row_leave,
                self,
            )
            layout.addWidget(row, alignment=Qt.AlignHCenter)

        divider = QWidget(self)
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {HAIRLINE};")
        layout.addWidget(divider)

        settings_pixmap = _glyph_pixmap(
            SETTINGS_GLYPH,
            QColor(255, 255, 255, 20),
            ICON_HOVER_PX,
            ICON_HOVER_RADIUS,
            font_px=21,
        )
        settings_row = Row(
            "",
            {"name": "Настройки"},
            settings_pixmap,
            self._select_settings,
            self._on_row_enter,
            self._on_row_leave,
            self,
        )
        layout.addWidget(settings_row, alignment=Qt.AlignHCenter)

    # ---- Строки: наведение/клик ------------------------------------------

    def _on_row_enter(self, row: Row) -> None:
        self._hide_timer.stop()
        hotkey = f"Alt+{row.number}" if row.number else ""
        self._chip.show_for(
            row.bind["name"],
            hotkey,
            row.mapToGlobal(QPoint(0, 0)),
            row.size(),
            self.side,
        )

    def _on_row_leave(self, _row: Row) -> None:
        self._chip.hide()

    def _select(self, row: Row) -> None:
        daemon.switch_to_app(row.bind)
        self.hide_panel()

    def _select_settings(self, _row: Row) -> None:
        self.hide_panel()
        entry_script = Path(__file__).resolve().parent.parent / "run.py"
        subprocess.Popen(
            [
                sys.executable,
                str(entry_script),
                "settings",
                "--config",
                str(self.config_path),
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    # ---- Уведомление о переключении по Alt+N (из daemon.py) ---------------

    def _on_udp_ready(self) -> None:
        while self._udp.hasPendingDatagrams():
            datagram = self._udp.receiveDatagram()
            number = bytes(datagram.data()).decode("ascii", errors="ignore").strip()
            self._on_switch_notified(number)

    def _on_switch_notified(self, number: str) -> None:
        self.show_panel()
        for row in self.findChildren(Row):
            if row.number == number:
                row.pulse()
                break

    # ---- Видимость ---------------------------------------------------------

    def enterEvent(self, event) -> None:
        self._hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)

    def _schedule_autohide(self) -> None:
        self._hide_timer.stop()
        if self.hide_delay_ms is not None:
            self._hide_timer.start(self.hide_delay_ms)

    def show_panel(self) -> None:
        if self._visible and not self._is_hiding:
            return

        self._is_hiding = False
        self._visible = True

        # Сбрасываем флаг: панель выехала, но мышь на неё пока не зашла
        self._mouse_entered = False

        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        area = screen.geometry()
        self.adjustSize()
        height = self.sizeHint().height()
        y = area.top() + (area.height() - height) // 2

        target_x = (
            area.right() - self.edge_offset - PANEL_WIDTH
            if self.side == "right"
            else area.left() + self.edge_offset
        )

        offscreen_x = area.right() if self.side == "right" else area.left() - PANEL_WIDTH

        if self.isHidden():
            self.move(offscreen_x, y)
            self.show()
            start_x = offscreen_x
        else:
            start_x = self.x()

        self._pos_anim.stop()
        self._pos_anim.setStartValue(QPoint(start_x, y))
        self._pos_anim.setEndValue(QPoint(target_x, y))
        self._pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._pos_anim.start()

        self._schedule_autohide()

    def hide_panel(self) -> None:
        if not self._visible or self._is_hiding:
            return

        self._is_hiding = True
        self._mouse_entered = False
        self._chip.hide()

        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        area = screen.geometry()

        offscreen_x = area.right() if self.side == "right" else area.left() - PANEL_WIDTH

        self._pos_anim.stop()
        self._pos_anim.setStartValue(self.pos())
        self._pos_anim.setEndValue(QPoint(offscreen_x, self.y()))
        self._pos_anim.setEasingCurve(QEasingCurve.InCubic)
        self._pos_anim.start()

        self._clear_of_edge = False
        self._dwell.update(False, time.monotonic())

    # ---- Тик: опрос края экрана (для edge-slide/hover) ---------------------

    def _tick(self) -> None:
        if self.trigger == "hotkey":
            return

        desktop = self._virtual_desktop_rect()
        cursor_pos = QCursor.pos()
        cursor_x = QCursor.pos().x()
        in_zone = is_cursor_at_edge(
            cursor_x, desktop.left(), desktop.right(), self.side
        )

        if self._visible and not self._is_hiding:
            screen = QApplication.screenAt(self.geometry().center())
            if screen:
                screen_geom = screen.geometry()
                panel_rect = self.geometry()

                if self.side == "left":
                    safe_rect = QRect(
                        screen_geom.left(),
                        screen_geom.top(),
                        panel_rect.right() - screen_geom.left(),
                        screen_geom.height()
                    )
                else:
                    safe_rect = QRect(
                        panel_rect.left(),
                        screen_geom.top(),
                        screen_geom.right() - panel_rect.left(),
                        screen_geom.height()
                    )

                # ИСПРАВЛЕНО: Закрываем, ТОЛЬКО ЕСЛИ мышь сначала зашла, а потом ушла
                if safe_rect.contains(cursor_pos):
                    self._mouse_entered = True
                elif self._mouse_entered:
                    self.hide_panel()

            return

            # 2. Логика открытия панели
        if not in_zone:
            self._clear_of_edge = True
            self._dwell.update(False, time.monotonic())
            return

        if not self._clear_of_edge:
            return

        if (
                self.trigger == "edge-slide"
                or (self.trigger == "hover" and self._dwell.update(True, time.monotonic()))
        ):
            self.show_panel()

    @staticmethod
    def _virtual_desktop_rect():
        rect = None
        for screen in QApplication.screens():
            geometry = screen.geometry()
            rect = geometry if rect is None else rect.united(geometry)
        return rect

    # ---- Фоновый поток для триггера "hotkey" -----------------------------

    def _start_hotkey_thread(self) -> None:
        def worker() -> None:
            if not win32api.register_hotkey(
                    PANEL_HOTKEY_ID, win32api.MODIFIERS["alt"], PANEL_HOTKEY_VK
            ):
                return
            try:
                while True:
                    result, msg = win32api.get_message()
                    if result == 0:
                        break
                    if (
                            msg.message == win32api.WM_HOTKEY
                            and msg.wParam == PANEL_HOTKEY_ID
                    ):
                        self._hotkey_signal.emit()
                    win32api.pump_message(msg)
            finally:
                win32api.unregister_hotkey(PANEL_HOTKEY_ID)

        threading.Thread(target=worker, daemon=True).start()


def run(config: dict[str, Any], config_path: Path) -> None:
    win32api.make_process_dpi_aware()
    app = QApplication(sys.argv)
    _panel = Panel(config, config_path)
    app.exec()