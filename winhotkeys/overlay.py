"""Оверлей-меню по Alt+0 в стиле macOS App Switcher (Cmd+Tab): ряд иконок
на полупрозрачной размытой панели + общее имя под рядом, обновляется при
наведении. Клик по иконке или цифра — переключиться (или запустить) и
закрыть.

Собственный процесс (см. daemon.open_overlay), а не часть цикла обработки
хоткеев — так GUI-луп customtkinter/tkinter не конфликтует с GetMessage-
циклом, который слушает горячие клавиши.

Использует customtkinter (и его зависимость Pillow) — единственные сторонние
библиотеки во всём проекте, осознанно взятые ради внешнего вида этого окна.
"""

from __future__ import annotations

import time
from typing import Any

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

from . import blur, daemon, icons, monitors
from .icons import get_icon_image

PANEL_BG = "#1e1e20"
TILE_HOVER_BG = "#3a3a3d"
FG = "#f5f5f7"
FG_MUTED = "#98989d"
ACCENT = "#0a84ff"

FONT_FAMILY = "AdwaitaMono Nerd Font Mono"
_FONT_FILE_REGULAR = "AdwaitaMonoNerdFontMono-Regular.ttf"
_FONT_FILE_BOLD = "AdwaitaMonoNerdFontMono-Bold.ttf"

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

ICON_SIZE = 44
ICON_HOVER_SIZE = 56
SQUIRCLE_RADIUS_RATIO = 0.24
ANIMATION_STEPS = 6
ANIMATION_DELAY_MS = 10

FADE_DURATION_S = 0.12
FADE_TARGET_ALPHA = 0.97


def _placeholder_color(name: str) -> str:
    return PALETTE[sum(map(ord, name)) % len(PALETTE)]


def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    candidates = (
        [_FONT_FILE_BOLD, "segoeuib.ttf", "seguisb.ttf", "segoeui.ttf"]
        if bold
        else [_FONT_FILE_REGULAR, "segoeui.ttf"]
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _squircle_mask(
    size: int, radius_ratio: float = SQUIRCLE_RADIUS_RATIO
) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    radius = int(size * radius_ratio)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def _to_squircle(img: Image.Image, size: int) -> Image.Image:
    img = img.convert("RGBA").resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), _squircle_mask(size))
    return out


def _placeholder_squircle(name: str, size: int) -> Image.Image:
    color = _placeholder_color(name)
    base = Image.new("RGBA", (size, size), color)
    draw = ImageDraw.Draw(base)
    font = _load_font(int(size * 0.5))
    letter = (name[:1] or "?").upper()
    bbox = draw.textbbox((0, 0), letter, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
        letter,
        font=font,
        fill="white",
    )
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(base, (0, 0), _squircle_mask(size))
    return out


class _Tile:
    """Одна иконка в ряду: анимированный размер (эффект Dock) + обработчики."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        number: str,
        bind: dict[str, Any],
        on_select,
        on_hover,
        source_path: str | None = None,
    ):
        self.number = number
        self.bind = bind
        self._on_select = on_select
        self._on_hover = on_hover
        self._anim_job = None
        self._current_size = ICON_SIZE

        base_image = get_icon_image(bind, source_path=source_path)
        self._base_image = (
            base_image
            if base_image is not None
            else _placeholder_squircle(bind["name"], ICON_HOVER_SIZE)
        )
        self._images_by_size: dict[int, ctk.CTkImage] = {}
        self.ctk_image = self._image_for_size(ICON_SIZE)

        self.frame = ctk.CTkFrame(
            parent, width=76, height=88, corner_radius=16, fg_color="transparent"
        )
        self.frame.grid_propagate(False)

        self.icon_label = ctk.CTkLabel(self.frame, text="", image=self.ctk_image)
        self.icon_label.place(relx=0.5, rely=0.38, anchor="center")

        self.badge = ctk.CTkLabel(
            self.frame,
            text=f"Alt+{number}",
            text_color=ACCENT,
            font=(FONT_FAMILY, 10, "bold"),
        )
        self.badge.place(relx=0.5, rely=0.86, anchor="center")

        for widget in (self.frame, self.icon_label, self.badge):
            widget.bind("<Button-1>", lambda _e: self._on_select(self.bind))
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

    def _enter(self, _event=None) -> None:
        self.frame.configure(fg_color=TILE_HOVER_BG)
        self._on_hover(self.bind["name"])
        self._animate_to(ICON_HOVER_SIZE)

    def _leave(self, _event=None) -> None:
        self.frame.configure(fg_color="transparent")
        self._on_hover(None)
        self._animate_to(ICON_SIZE)

    def _animate_to(self, target: int) -> None:
        if self._anim_job is not None:
            self.frame.after_cancel(self._anim_job)
            self._anim_job = None
        self._step(target, ANIMATION_STEPS)

    def _image_for_size(self, size: int) -> ctk.CTkImage:
        image = self._images_by_size.get(size)
        if image is None:
            scaled = _to_squircle(self._base_image, size)
            image = ctk.CTkImage(
                light_image=scaled, dark_image=scaled, size=(size, size)
            )
            self._images_by_size[size] = image
        return image

    def _step(self, target: int, steps_left: int) -> None:
        if steps_left <= 0:
            self._current_size = target
            self.ctk_image = self._image_for_size(target)
            self.icon_label.configure(image=self.ctk_image)
            self._anim_job = None
            return
        self._current_size += (target - self._current_size) / steps_left
        size = round(self._current_size)
        self.ctk_image = self._image_for_size(size)
        self.icon_label.configure(image=self.ctk_image)
        self._anim_job = self.frame.after(
            ANIMATION_DELAY_MS, lambda: self._step(target, steps_left - 1)
        )


def show(config: dict[str, Any]) -> None:
    items = sorted(config.items(), key=lambda kv: kv[0])
    if not items:
        return

    ctk.set_appearance_mode("dark")

    root = ctk.CTk()
    root.withdraw()  # ничего не рисуем на экране, пока не вычислим позицию
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.0)
    root.configure(fg_color=PANEL_BG)

    chosen: dict[str, Any] = {}

    def select(bind: dict[str, Any]) -> None:
        chosen["bind"] = bind
        root.destroy()

    def close(_event=None) -> None:
        root.destroy()

    def on_hover(name: str | None) -> None:
        name_label.configure(text=name or "")

    panel = ctk.CTkFrame(root, corner_radius=0, fg_color=PANEL_BG)
    panel.pack(fill="both", expand=True)

    row = ctk.CTkFrame(panel, fg_color="transparent")
    row.pack(padx=20, pady=(22, 6))

    icon_sources = icons.resolve_icon_sources([bind for _, bind in items])
    tiles: list[_Tile] = []
    for col, (number, bind) in enumerate(items):
        tile = _Tile(
            row,
            number,
            bind,
            on_select=select,
            on_hover=on_hover,
            source_path=icon_sources.get(id(bind)),
        )
        tile.frame.grid(row=0, column=col, padx=4)
        tiles.append(tile)

    name_label = ctk.CTkLabel(
        panel, text="", text_color=FG, font=(FONT_FAMILY, 12, "bold")
    )
    name_label.pack(pady=(0, 8))

    hint_label = ctk.CTkLabel(
        panel,
        text="выберите цифру или кликните · Esc — отмена",
        text_color=FG_MUTED,
        font=(FONT_FAMILY, 9),
    )
    hint_label.pack(pady=(0, 16))

    hwnd = blur.get_window_hwnd(root)
    blur.enable_window_blur(hwnd)
    blur.enable_rounded_corners(hwnd)

    def on_key(event) -> None:
        if event.keysym == "Escape":
            close()
            return
        if event.char and event.char in config:
            select(config[event.char])

    root.bind("<Key>", on_key)
    root.after(150, lambda: root.bind("<FocusOut>", close))

    def fade_in() -> None:
        # По прошедшему времени, а не фиксированными шагами альфы — так
        # плавность не зависит от того, насколько точно Tk уложился в
        # запрошенные интервалы между кадрами (иначе на "дёргающихся"
        # тиках шаги альфы выглядят прыжками, а не плавным затуханием).
        start = time.perf_counter()

        def step() -> None:
            progress = min((time.perf_counter() - start) / FADE_DURATION_S, 1.0)
            root.attributes("-alpha", progress * FADE_TARGET_ALPHA)
            if progress < 1.0:
                root.after(8, step)

        step()

    def center_and_reveal() -> None:
        # Показываем окно (deiconify) ещё при alpha=0 — до этого момента оно
        # withdraw()'нуто и вообще не отрисовывается, поэтому пересчёт
        # размера/масштаба customtkinter (который окончательно происходит
        # только после первого маппинга окна) никак не виден пользователю —
        # ни как "окно мелькнуло не в том месте", ни как скачок размера.
        #
        # Центрируем на мониторе под курсором, а не на "экране" в понимании
        # Tk — winfo_screenwidth/height на мультимониторных системах не
        # соответствует физическому монитору, на котором сидит пользователь.
        root.deiconify()
        root.update_idletasks()
        width, height = root.winfo_width(), root.winfo_height()
        left, top, right, bottom = monitors.get_work_area_at_cursor()
        x = left + (right - left - width) // 2
        y = top + (bottom - top - height) // 2
        root.geometry(f"+{x}+{y}")
        root.update_idletasks()
        root.focus_force()
        root.grab_set()
        fade_in()

    root.after(15, center_and_reveal)
    root.mainloop()

    bind = chosen.get("bind")
    if bind is not None:
        daemon.switch_to_app(bind)
