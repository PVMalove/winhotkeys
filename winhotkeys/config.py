"""Хранение и валидация привязок «клавиша -> программа» в JSON-файле."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

VALID_MODIFIERS = {"alt", "ctrl", "shift", "win"}
VALID_TRIGGERS = {"edge-slide", "hover", "hotkey"}
VALID_SIDES = {"right", "left"}
VALID_HIDE_DELAYS = {1, 3, 6, None}


def default_config_path() -> Path:
    base = os.environ.get("APPDATA", str(Path.home()))
    return Path(base) / "winhotkeys" / "config.json"


def default_binds() -> dict[str, Any]:
    return {
        "1": {
            "name": "VS Code",
            "command": "code",
            "processes": ["Code"],
            "modifiers": ["alt"],
        },
        "2": {
            "name": "PowerShell 7",
            "command": 'wt.exe -p "PowerShell"',
            "processes": ["WindowsTerminal", "pwsh"],
            "modifiers": ["alt"],
        },
    }


def default_panel_settings() -> dict[str, Any]:
    return {
        "trigger": "edge-slide",
        "side": "right",
        "hide_delay": 3,
        "icon_spacing": 6,  # px между иконками
        "edge_offset": 24,  # px от края монитора до панели
    }


def default_config() -> dict[str, Any]:
    return {"binds": default_binds(), "panel": default_panel_settings()}


def _migrate_if_flat(data: dict[str, Any]) -> dict[str, Any]:
    """Старые config.json — плоский словарь биндов ("1".."9" -> bind), без
    ключей "binds"/"panel". Оборачивает его в новый вложенный формат при
    чтении; ничего не пишет на диск — файл переходит в новый формат только
    при следующем save_config (add/remove/изменение настроек панели)."""
    if "binds" in data or "panel" in data:
        return data
    return {"binds": data, "panel": default_panel_settings()}


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_config()
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data = _migrate_if_flat(data)
    # Заполняет ключи, отсутствующие в файлах, сохранённых до их
    # появления (например icon_spacing/edge_offset) — дефолтами, не
    # трогая уже присутствующие значения.
    data["panel"] = {**default_panel_settings(), **data.get("panel", {})}
    return data


def save_config(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def validate_bind(
    number: str,
    name: str,
    command: str,
    processes: list[str],
    modifiers: list[str],
) -> None:
    if not (number.isdigit() and 1 <= int(number) <= 9):
        raise ValueError("номер привязки должен быть цифрой от 1 до 9 (0 зарезервирован под панель)")
    if not name.strip():
        raise ValueError("не указано имя программы")
    if not command.strip():
        raise ValueError("не указана команда запуска")
    if not processes:
        raise ValueError("нужно указать хотя бы один процесс для поиска окон")
    if not modifiers:
        raise ValueError("нужно указать хотя бы один модификатор")
    unknown = set(modifiers) - VALID_MODIFIERS
    if unknown:
        raise ValueError(f"неизвестные модификаторы: {', '.join(sorted(unknown))}")


def add_bind(
    config: dict[str, Any],
    number: str,
    name: str,
    command: str,
    processes: list[str],
    modifiers: list[str],
) -> dict[str, Any]:
    """Возвращает НОВЫЙ словарь конфигурации с добавленной/заменённой
    привязкой; исходный config не мутируется."""
    validate_bind(number, name, command, processes, modifiers)
    new_config = dict(config)
    new_config[number] = {
        "name": name,
        "command": command,
        "processes": list(processes),
        "modifiers": list(modifiers),
    }
    return new_config


def next_free_bind_number(binds: dict[str, Any]) -> str | None:
    """Первая свободная цифра 1-9 для новой привязки (0 не рассматривается
    — зарезервирован под панель), либо None, если все заняты."""
    for number in "123456789":
        if number not in binds:
            return number
    return None


def remove_bind(config: dict[str, Any], number: str) -> dict[str, Any]:
    if number not in config:
        raise KeyError(f"привязка {number} не найдена")
    new_config = dict(config)
    del new_config[number]
    return new_config
