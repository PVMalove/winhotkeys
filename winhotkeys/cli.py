"""Консольный интерфейс: python run.py start|stop|status|list|add|remove."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as config_mod
from . import daemon


def _config_path(args: argparse.Namespace) -> Path:
    return Path(args.config) if getattr(args, "config", None) else config_mod.default_config_path()


def cmd_start(args: argparse.Namespace) -> int:
    """Включение: в фоне поднимает и слушатель горячих клавиш (Alt+1..9),
    и резидентную боковую панель. --foreground — только про слушатель
    (отладочный режим в текущей консоли), панель им не затрагивается."""
    config_path = _config_path(args)
    pid_path = daemon.default_pid_path()

    if args.foreground:
        cfg = config_mod.load_config(config_path)
        print(f"Загружено привязок: {len(cfg['binds'])}. Работаю в этой консоли (Ctrl+C — остановить)...")
        try:
            daemon.run_loop(cfg["binds"])
        except KeyboardInterrupt:
            print("Остановлено пользователем.")
        return 0

    print(daemon.start_background(pid_path, config_path))
    print(daemon.start_panel_background(daemon.default_panel_pid_path(), config_path))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Служебная команда: реальный цикл обработки, который выполняется
    внутри фонового процесса, запущенного из cmd_start."""
    config_path = _config_path(args)
    cfg = config_mod.load_config(config_path)
    daemon.run_loop(cfg["binds"])
    return 0


def cmd_panel(args: argparse.Namespace) -> int:
    """Служебная команда: резидентная боковая панель (запускается из
    daemon.start_panel_background в отдельном фоновом процессе, один раз
    при старте — не заново при каждом открытии)."""
    try:
        from . import panel
    except ImportError as exc:
        print(
            f"Ошибка: не установлен PySide6, нужен для панели ({exc}).\n"
            "Установите: pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    config_path = _config_path(args)
    cfg = config_mod.load_config(config_path)
    panel.run(cfg, config_path)
    return 0


def cmd_settings(args: argparse.Namespace) -> int:
    """Открывает окно настроек панели (раздел «Панель и Поведение»);
    изменения применяются со следующего запуска (stop, затем start —
    как и для изменений привязок)."""
    try:
        from . import settings_window
    except ImportError as exc:
        print(
            f"Ошибка: не установлен customtkinter, нужен для окна настроек ({exc}).\n"
            "Установите: pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    settings_window.show(_config_path(args))
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    """Выключение: останавливает и слушатель, и резидентную панель, если
    они запущены."""
    print(daemon.stop(daemon.default_pid_path()))
    print(daemon.stop(daemon.default_panel_pid_path(), label="Панель", gender="f"))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    print(daemon.status(daemon.default_pid_path()))
    print(daemon.status(daemon.default_panel_pid_path(), label="Панель", gender="f"))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    cfg = config_mod.load_config(_config_path(args))
    binds = cfg["binds"]
    if not binds:
        print("Привязок нет.")
        return 0
    for number, bind in sorted(binds.items()):
        mods = "+".join(m.capitalize() for m in bind["modifiers"])
        processes = ", ".join(bind["processes"])
        print(f"{mods}+{number}  ->  {bind['name']}  (команда: {bind['command']}; процессы: {processes})")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    """Добавляет (или заменяет) привязку клавиши к программе."""
    config_path = _config_path(args)
    cfg = config_mod.load_config(config_path)
    modifiers = args.mod or ["alt"]
    try:
        cfg["binds"] = config_mod.add_bind(
            cfg["binds"],
            number=args.number,
            name=args.name,
            command=args.command,
            processes=args.process,
            modifiers=modifiers,
        )
    except ValueError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    config_mod.save_config(config_path, cfg)
    combo = "+".join(m.capitalize() for m in modifiers)
    print(f"Добавлена привязка {combo}+{args.number} -> {args.name}")
    print("Перезапустите слушатель (stop, затем start), чтобы изменения применились.")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    config_path = _config_path(args)
    cfg = config_mod.load_config(config_path)
    try:
        cfg["binds"] = config_mod.remove_bind(cfg["binds"], args.number)
    except KeyError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    config_mod.save_config(config_path, cfg)
    print(f"Привязка {args.number} удалена.")
    print("Перезапустите слушатель (stop, затем start), чтобы изменения применились.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config",
        help=r"Путь к файлу конфигурации (по умолчанию %%APPDATA%%\winhotkeys\config.json)",
    )

    parser = argparse.ArgumentParser(
        prog="winhotkeys",
        description="Глобальные горячие клавиши для переключения между окнами программ (Windows, без сторонних утилит).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", parents=[common], help="Включить прослушивание горячих клавиш")
    p_start.add_argument("--foreground", action="store_true", help="Не уходить в фон, работать в этой консоли")
    p_start.set_defaults(func=cmd_start)

    p_run = sub.add_parser("run", parents=[common], help=argparse.SUPPRESS)
    p_run.set_defaults(func=cmd_run)

    p_panel = sub.add_parser("panel", parents=[common], help=argparse.SUPPRESS)
    p_panel.set_defaults(func=cmd_panel)

    p_settings = sub.add_parser("settings", parents=[common], help="Открыть окно настроек панели")
    p_settings.set_defaults(func=cmd_settings)

    p_stop = sub.add_parser("stop", help="Выключить прослушивание горячих клавиш и панель")
    p_stop.set_defaults(func=cmd_stop)

    p_status = sub.add_parser("status", help="Проверить, запущен ли слушатель")
    p_status.set_defaults(func=cmd_status)

    p_list = sub.add_parser("list", parents=[common], help="Показать текущие привязки")
    p_list.set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", parents=[common], help="Добавить/заменить привязку клавиши")
    p_add.add_argument("number", help="Цифра 1-9 (0 зарезервирован под панель)")
    p_add.add_argument("name", help="Отображаемое имя программы")
    p_add.add_argument("command", help='Команда запуска, например code или "wt.exe -p PowerShell"')
    p_add.add_argument(
        "--process",
        action="append",
        required=True,
        help="Имя процесса для поиска окон (можно указать несколько раз)",
    )
    p_add.add_argument(
        "--mod",
        action="append",
        help="Модификатор: alt/ctrl/shift/win (можно несколько раз; по умолчанию alt)",
    )
    p_add.set_defaults(func=cmd_add)

    p_remove = sub.add_parser("remove", parents=[common], help="Удалить привязку")
    p_remove.add_argument("number")
    p_remove.set_defaults(func=cmd_remove)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
