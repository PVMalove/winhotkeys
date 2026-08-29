"""Окно настроек панели: «Панель и Поведение» (триггер/сторона/автоскрытие)
и «Управление Горячими Клавишами» (список привязок, добавление, удаление)
— оба раздела функциональные. «О Программе» — статичная информационная
карточка.

Изменения применяются сразу в config.json, без отдельной кнопки
«Сохранить» — как в нативных настройках Windows 11. Резидентная панель
подхватывает изменения секции "panel" при следующем перезапуске (stop,
затем start); изменения привязок здесь работают так же, как через CLI
`add`/`remove` — тот же config_mod, тот же файл.
"""

from __future__ import annotations

import tkinter
import traceback
from pathlib import Path

import customtkinter as ctk

from . import config as config_mod

BG = "#1e1e20"
CARD_BG = "#252528"
FG = "#f5f5f7"
FG_MUTED = "#98989d"
ACCENT = "#0a84ff"
DANGER = "#e5484d"

TRIGGER_OPTIONS = [
    ("edge-slide", "Скольжение от края", "По умолчанию — свайп с края экрана открывает панель"),
    ("hover", "Наведение на край экрана", "Панель появляется, пока курсор у края, и прячется при уходе"),
    ("hotkey", "Кастомная горячая клавиша", "Alt+0 — раньше это был единственный способ открыть меню"),
]

HIDE_DELAY_LABELS = {1: "Быстро (1 сек)", 3: "Средне (3 сек)", 6: "Долго (6 сек)", None: "Никогда"}
HIDE_DELAY_BY_LABEL = {label: value for value, label in HIDE_DELAY_LABELS.items()}

NAV_SECTIONS = [
    ("panel", "Панель и Поведение"),
    ("hotkeys", "Управление Горячими Клавишами"),
    ("about", "О Программе"),
]


class SettingsWindow:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config = config_mod.load_config(config_path)

        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk()
        self.root.title("WinHotkeys Настройки")
        self.root.geometry("900x680")
        self.root.configure(fg_color=BG)
        # При переключении раздела старые виджеты уничтожаются сразу
        # (см. _show_section), а customtkinter иногда успевает поставить
        # в очередь их отложенную перерисовку (`<Configure>`) до этого —
        # безобидный TclError "invalid command name", не влияющий на
        # работу окна, но иначе шумящий в консоли при каждом переключении.
        self.root.report_callback_exception = self._on_tk_callback_exception

        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._binds_list: ctk.CTkScrollableFrame | None = None
        self._build_nav()

        self.content = ctk.CTkFrame(self.root, fg_color="transparent")
        self.content.pack(side="left", fill="both", expand=True, padx=16, pady=16)

        self._show_section("panel")

    # ---- Навигация -------------------------------------------------------

    def _build_nav(self) -> None:
        nav = ctk.CTkFrame(self.root, width=200, fg_color="transparent")
        nav.pack(side="left", fill="y", padx=(12, 0), pady=12)
        nav.pack_propagate(False)

        for key, label in NAV_SECTIONS:
            btn = ctk.CTkButton(
                nav,
                text=label,
                anchor="w",
                fg_color="transparent",
                text_color=FG_MUTED,
                command=lambda k=key: self._show_section(k),
            )
            btn.pack(fill="x", pady=2)
            self._nav_buttons[key] = btn

    def _show_section(self, key: str) -> None:
        for nav_key, btn in self._nav_buttons.items():
            active = nav_key == key
            btn.configure(fg_color=ACCENT if active else "transparent", text_color=FG if active else FG_MUTED)

        for child in self.content.winfo_children():
            child.destroy()
        self._binds_list = None

        if key == "panel":
            self._build_panel_section(self.content)
        elif key == "hotkeys":
            self._build_hotkeys_section(self.content)
        else:
            self._build_about_section(self.content)

    # ---- Панель и Поведение ----------------------------------------------

    def _build_panel_section(self, parent: ctk.CTkBaseClass) -> None:
            # Заменили CTkScrollableFrame на обычный CTkFrame
            body = ctk.CTkFrame(parent, fg_color="transparent")
            body.pack(fill="both", expand=True)

            ctk.CTkLabel(body, text="Панель и Поведение", text_color=FG, font=("Segoe UI", 18, "bold")).pack(
                anchor="w", pady=(0, 12)
            )

            self._build_trigger_group(body)
            self._build_side_group(body)
            self._build_hide_delay_group(body)
            self._build_spacing_group(body)
            self._build_edge_offset_group(body)

    def _build_trigger_group(self, parent: ctk.CTkBaseClass) -> None:
        group = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=10)
        group.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            group, text="КАК ОТКРЫТЬ ПАНЕЛЬ?", text_color=FG_MUTED, font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", padx=14, pady=(12, 4))

        self._trigger_var = ctk.StringVar(value=self.config["panel"]["trigger"])
        for value, title, desc in TRIGGER_OPTIONS:
            row = ctk.CTkFrame(group, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=4)
            ctk.CTkRadioButton(
                row,
                text=title,
                value=value,
                variable=self._trigger_var,
                text_color=FG,
                command=self._on_trigger_change,
            ).pack(anchor="w")
            ctk.CTkLabel(row, text=desc, text_color=FG_MUTED, font=("Segoe UI", 10)).pack(
                anchor="w", padx=(28, 0), pady=(0, 6)
            )

    def _build_side_group(self, parent: ctk.CTkBaseClass) -> None:
        group = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=10)
        group.pack(fill="x", pady=(0, 12))
        row = ctk.CTkFrame(group, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(row, text="Сторона экрана", text_color=FG, font=("Segoe UI", 13, "bold")).pack(side="left")

        self._side_seg = ctk.CTkSegmentedButton(row, values=["Лево", "Право"], command=self._on_side_change)
        self._side_seg.set("Право" if self.config["panel"]["side"] == "right" else "Лево")
        self._side_seg.pack(side="right")

    def _build_hide_delay_group(self, parent: ctk.CTkBaseClass) -> None:
        group = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=10)
        group.pack(fill="x", pady=(0, 12))
        row = ctk.CTkFrame(group, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(row, text="Время скрытия панели", text_color=FG, font=("Segoe UI", 13, "bold")).pack(
            side="left"
        )

        self._hide_menu = ctk.CTkOptionMenu(
            row, values=list(HIDE_DELAY_LABELS.values()), command=self._on_hide_delay_change
        )
        self._hide_menu.set(HIDE_DELAY_LABELS[self.config["panel"]["hide_delay"]])
        self._hide_menu.pack(side="right")

    def _build_spacing_group(self, parent: ctk.CTkBaseClass) -> None:
        group = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=10)
        group.pack(fill="x", pady=(0, 12))
        row = ctk.CTkFrame(group, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(row, text="Расстояние между иконками", text_color=FG, font=("Segoe UI", 13, "bold")).pack(
            side="left"
        )
        self._spacing_value = ctk.CTkLabel(row, text=str(self.config["panel"]["icon_spacing"]), text_color=FG_MUTED, width=28)
        self._spacing_value.pack(side="right")
        self._spacing_slider = ctk.CTkSlider(row, from_=0, to=20, number_of_steps=20, command=self._on_spacing_change)
        self._spacing_slider.set(self.config["panel"]["icon_spacing"])
        self._spacing_slider.pack(side="right", padx=(0, 10), fill="x", expand=True)

    def _build_edge_offset_group(self, parent: ctk.CTkBaseClass) -> None:
        group = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=10)
        group.pack(fill="x", pady=(0, 12))
        row = ctk.CTkFrame(group, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(row, text="Отступ от края экрана", text_color=FG, font=("Segoe UI", 13, "bold")).pack(
            side="left"
        )
        self._edge_offset_value = ctk.CTkLabel(
            row, text=str(self.config["panel"]["edge_offset"]), text_color=FG_MUTED, width=28
        )
        self._edge_offset_value.pack(side="right")
        self._edge_offset_slider = ctk.CTkSlider(
            row, from_=0, to=100, number_of_steps=100, command=self._on_edge_offset_change
        )
        self._edge_offset_slider.set(self.config["panel"]["edge_offset"])
        self._edge_offset_slider.pack(side="right", padx=(0, 10), fill="x", expand=True)

    def _on_spacing_change(self, value: float) -> None:
        value = int(round(value))
        self._spacing_value.configure(text=str(value))
        self.config["panel"]["icon_spacing"] = value
        self._save()

    def _on_edge_offset_change(self, value: float) -> None:
        value = int(round(value))
        self._edge_offset_value.configure(text=str(value))
        self.config["panel"]["edge_offset"] = value
        self._save()

    def _on_trigger_change(self) -> None:
        self.config["panel"]["trigger"] = self._trigger_var.get()
        self._save()

    def _on_side_change(self, label: str) -> None:
        self.config["panel"]["side"] = "right" if label == "Право" else "left"
        self._save()

    def _on_hide_delay_change(self, label: str) -> None:
        self.config["panel"]["hide_delay"] = HIDE_DELAY_BY_LABEL[label]
        self._save()

    # ---- Управление Горячими Клавишами ------------------------------------

    def _build_hotkeys_section(self, parent: ctk.CTkBaseClass) -> None:
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            header, text="Управление Горячими Клавишами", text_color=FG, font=("Segoe UI", 18, "bold")
        ).pack(side="left")
        ctk.CTkButton(header, text="+ Добавить приложение", command=self._open_add_dialog).pack(side="right")

        self._binds_list = ctk.CTkScrollableFrame(parent, fg_color=CARD_BG, corner_radius=10)
        self._binds_list.pack(fill="both", expand=True)
        self._refresh_binds_list()

    def _refresh_binds_list(self) -> None:
        if self._binds_list is None:
            return
        for child in self._binds_list.winfo_children():
            child.destroy()

        binds = self.config["binds"]
        if not binds:
            ctk.CTkLabel(self._binds_list, text="Привязок нет.", text_color=FG_MUTED).pack(padx=14, pady=14)
            return

        for number, bind in sorted(binds.items()):
            row = ctk.CTkFrame(self._binds_list, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=4)

            combo = "+".join(m.capitalize() for m in bind["modifiers"]) + f"+{number}"
            ctk.CTkLabel(
                row, text=combo, text_color=ACCENT, font=("Consolas", 12, "bold"), width=76, anchor="w"
            ).pack(side="left")

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=(10, 0))
            ctk.CTkLabel(info, text=bind["name"], text_color=FG, font=("Segoe UI", 13, "bold"), anchor="w").pack(
                anchor="w"
            )
            detail = f'{bind["command"]}  ·  процессы: {", ".join(bind["processes"])}'
            ctk.CTkLabel(info, text=detail, text_color=FG_MUTED, font=("Segoe UI", 10), anchor="w").pack(
                anchor="w"
            )

            ctk.CTkButton(
                row,
                text="✕",
                width=28,
                height=28,
                corner_radius=8,
                fg_color="transparent",
                hover_color=DANGER,
                text_color=FG_MUTED,
                command=lambda n=number: self._remove_bind(n),
            ).pack(side="right")

    def _remove_bind(self, number: str) -> None:
        self.config["binds"] = config_mod.remove_bind(self.config["binds"], number)
        self._save()
        self._refresh_binds_list()

    def _open_add_dialog(self) -> None:
        _AddBindDialog(self)

    def add_bind_and_refresh(
        self, number: str, name: str, command: str, processes: list[str], modifiers: list[str]
    ) -> None:
        """Валидирует и сохраняет новую привязку — вызывается диалогом
        добавления; бросает ValueError с текстом ошибки для показа в форме."""
        self.config["binds"] = config_mod.add_bind(
            self.config["binds"], number=number, name=name, command=command, processes=processes, modifiers=modifiers
        )
        self._save()
        self._refresh_binds_list()

    # ---- О Программе -------------------------------------------------------

    def _build_about_section(self, parent: ctk.CTkBaseClass) -> None:
        ctk.CTkLabel(parent, text="О Программе", text_color=FG, font=("Segoe UI", 18, "bold")).pack(
            anchor="w", pady=(0, 12)
        )
        card = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=10)
        card.pack(fill="x")
        ctk.CTkLabel(card, text="WinHotkeys", text_color=FG, font=("Segoe UI", 15, "bold")).pack(
            anchor="w", padx=16, pady=(16, 2)
        )
        ctk.CTkLabel(
            card,
            text=(
                "Глобальные горячие клавиши для переключения между окнами программ "
                "и быстрый доступ к приложениям через боковую панель."
            ),
            text_color=FG_MUTED,
            font=("Segoe UI", 11),
            anchor="w",
            justify="left",
            wraplength=420,
        ).pack(anchor="w", padx=16, pady=(0, 16))

    # ---- Общее -------------------------------------------------------------

    @staticmethod
    def _on_tk_callback_exception(exc_type, exc_value, exc_tb) -> None:
        if exc_type is tkinter.TclError:
            return
        traceback.print_exception(exc_type, exc_value, exc_tb)

    def _save(self) -> None:
        config_mod.save_config(self.config_path, self.config)

    def run(self) -> None:
        self.root.mainloop()


class _AddBindDialog(ctk.CTkToplevel):
    """Модальная форма добавления привязки — number/name/command/processes/
    modifiers, те же поля и та же валидация (config.add_bind), что и у
    CLI-команды `winhotkeys add`."""

    def __init__(self, owner: SettingsWindow):
        super().__init__(owner.root)
        self.owner = owner
        self.title("Новое приложение")
        self.geometry("800x620")
        self.configure(fg_color=BG)
        self.transient(owner.root)
        self.grab_set()

        self._modifier_vars: dict[str, ctk.BooleanVar] = {}
        self._build()

    def _build(self) -> None:
        pad = {"padx": 16}

        ctk.CTkLabel(self, text="Номер (1-9)", text_color=FG_MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(16, 2), **pad
        )
        next_number = config_mod.next_free_bind_number(self.owner.config["binds"]) or ""
        self._number_entry = ctk.CTkEntry(self, width=60)
        self._number_entry.insert(0, next_number)
        self._number_entry.pack(anchor="w", **pad)

        ctk.CTkLabel(self, text="Имя программы", text_color=FG_MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(12, 2), **pad
        )
        self._name_entry = ctk.CTkEntry(self)
        self._name_entry.pack(fill="x", **pad)

        ctk.CTkLabel(
            self, text="Команда запуска", text_color=FG_MUTED, font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", pady=(12, 2), **pad)
        self._command_entry = ctk.CTkEntry(self, placeholder_text='code или "wt.exe -p PowerShell"')
        self._command_entry.pack(fill="x", **pad)

        ctk.CTkLabel(
            self, text="Процессы (через запятую)", text_color=FG_MUTED, font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", pady=(12, 2), **pad)
        self._processes_entry = ctk.CTkEntry(self, placeholder_text="Code")
        self._processes_entry.pack(fill="x", **pad)

        ctk.CTkLabel(self, text="Модификаторы", text_color=FG_MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(12, 2), **pad
        )
        mods_row = ctk.CTkFrame(self, fg_color="transparent")
        mods_row.pack(anchor="w", **pad)
        for mod in ("alt", "ctrl", "shift", "win"):
            var = ctk.BooleanVar(value=(mod == "alt"))
            self._modifier_vars[mod] = var
            ctk.CTkCheckBox(mods_row, text=mod.capitalize(), variable=var, text_color=FG, width=70).pack(
                side="left"
            )

        self._error_label = ctk.CTkLabel(self, text="", text_color=DANGER, wraplength=340, justify="left")
        self._error_label.pack(anchor="w", pady=(12, 0), **pad)

        ctk.CTkButton(self, text="Добавить", command=self._submit).pack(pady=(14, 16), **pad)

    def _submit(self) -> None:
        processes = [p.strip() for p in self._processes_entry.get().split(",") if p.strip()]
        modifiers = [mod for mod, var in self._modifier_vars.items() if var.get()]
        try:
            self.owner.add_bind_and_refresh(
                number=self._number_entry.get().strip(),
                name=self._name_entry.get().strip(),
                command=self._command_entry.get().strip(),
                processes=processes,
                modifiers=modifiers,
            )
        except ValueError as exc:
            self._error_label.configure(text=str(exc))
            return
        self.destroy()


def show(config_path: Path) -> None:
    SettingsWindow(config_path).run()
