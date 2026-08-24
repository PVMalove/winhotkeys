"""Хранение и валидация привязок «клавиша -> программа» в JSON-файле."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

VALID_MODIFIERS = {"alt", "ctrl", "shift", "win"}


def default_config_path() -> Path:
    base = os.environ.get("APPDATA", str(Path.home()))
    return Path(base) / "winhotkeys" / "config.json"


def default_config() -> dict[str, Any]:
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


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_config()
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


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
        raise ValueError("номер привязки должен быть цифрой от 1 до 9 (0 зарезервирован под меню Alt+0)")
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


def remove_bind(config: dict[str, Any], number: str) -> dict[str, Any]:
    if number not in config:
        raise KeyError(f"привязка {number} не найдена")
    new_config = dict(config)
    del new_config[number]
    return new_config
