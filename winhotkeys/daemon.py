"""Управление фоновым слушателем горячих клавиш: запуск, остановка,
статус, и сам цикл обработки сообщений."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import win32api
from .core import find_index, pick_next_action

PID_FILE_NAME = "daemon.pid"
OVERLAY_PID_FILE_NAME = "overlay.pid"

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Alt+0 зарезервирован под меню-оверлей (см. overlay.py), не участвует в
# пользовательских привязках (config.validate_bind запрещает номер "0").
OVERLAY_HOTKEY_ID = 0
OVERLAY_VK = 0x30  # VK_0


def default_pid_path() -> Path:
    base = os.environ.get("APPDATA", str(Path.home()))
    return Path(base) / "winhotkeys" / PID_FILE_NAME


def default_overlay_pid_path() -> Path:
    base = os.environ.get("APPDATA", str(Path.home()))
    return Path(base) / "winhotkeys" / OVERLAY_PID_FILE_NAME


def is_process_running(pid: int) -> bool:
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def _is_our_daemon(pid: int) -> bool:
    """Помимо того, что процесс с таким PID вообще существует, проверяет,
    что это действительно наш python-процесс — а не то, во что Windows
    успела переиспользовать этот PID после того, как настоящий демон уже
    завершился (например, из-за особенностей фонового запуска через
    инструменты кодового ассистента — процесс мог не пережить его сессию).
    Без этой проверки status() мог бы соврать, что демон ещё работает, а
    stop() — попытаться завершить чужой процесс (в лучшем случае получив
    PermissionError, в худшем — реально прибив что-то постороннее)."""
    if not is_process_running(pid):
        return False
    from .icons import get_process_image_path

    image_path = get_process_image_path(pid)
    if image_path is None:
        return False
    return Path(image_path).name.lower() == Path(sys.executable).name.lower()


def read_pid(pid_path: Path) -> int | None:
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text().strip())
    except ValueError:
        return None


def status(pid_path: Path) -> str:
    pid = read_pid(pid_path)
    if pid is not None and _is_our_daemon(pid):
        return f"Слушатель запущен (PID {pid})"
    return "Слушатель не запущен"


def stop(pid_path: Path) -> str:
    pid = read_pid(pid_path)
    if pid is None or not is_process_running(pid):
        pid_path.unlink(missing_ok=True)
        return "Слушатель не был запущен"

    if not _is_our_daemon(pid):
        # PID из pid-файла Windows уже отдала другому процессу — настоящий
        # демон, скорее всего, уже завершился сам. Не трогаем чужой процесс.
        pid_path.unlink(missing_ok=True)
        return (
            f"Слушатель не был запущен (PID {pid} в pid-файле уже "
            "принадлежит другому процессу, вероятно демон завершился сам)"
        )

    try:
        os.kill(pid, 15)  # на Windows Python транслирует это в TerminateProcess
    except OSError as exc:
        pid_path.unlink(missing_ok=True)
        return f"Не удалось остановить процесс PID {pid} ({exc}); pid-файл очищен"

    pid_path.unlink(missing_ok=True)
    return f"Слушатель (PID {pid}) остановлен"


def start_background(pid_path: Path, config_path: Path) -> str:
    """Включение: поднимает слушатель в отдельном фоновом процессе
    (без консольного окна) и запоминает его PID."""
    existing = read_pid(pid_path)
    if existing is not None and _is_our_daemon(existing):
        return f"Слушатель уже запущен (PID {existing})"

    entry_script = Path(__file__).resolve().parent.parent / "run.py"
    creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    proc = subprocess.Popen(
        [sys.executable, str(entry_script), "run", "--config", str(config_path)],
        creationflags=creationflags,
        close_fds=True,
    )

    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(proc.pid))
    return f"Слушатель запущен в фоне (PID {proc.pid})"


def launch_app(command: str) -> None:
    subprocess.Popen(command, shell=True)


def open_overlay(config_path: Path | None = None) -> None:
    """Показывает меню-оверлей (Alt+0) в отдельном коротком процессе.

    Не плодит окна, если оверлей уже открыт (проверка по своему pid-файлу).
    Вывод (в т.ч. ошибки — например, если не установлен customtkinter)
    уходит в overlay.log, иначе в фоновом процессе он был бы просто потерян.
    """
    pid_path = default_overlay_pid_path()
    existing = read_pid(pid_path)
    if existing is not None and is_process_running(existing):
        return

    entry_script = Path(__file__).resolve().parent.parent / "run.py"
    args = [sys.executable, str(entry_script), "overlay"]
    if config_path is not None:
        args += ["--config", str(config_path)]

    pid_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = pid_path.parent / "overlay.log"
    with open(log_path, "a", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            args,
            stdout=log_file,
            stderr=log_file,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    pid_path.write_text(str(proc.pid))


def switch_to_app(
    bind: dict[str, Any], active_window_getter=win32api.user32.GetForegroundWindow
) -> None:
    """Реализация Alt+N: если процесс не запущен — запускаем программу; если
    запущен — переключаемся на следующее его окно по кругу, а с последнего
    окна (или когда окно всего одно) — сворачиваем вместо зацикливания."""
    pids = win32api.get_process_ids_by_name_cached(bind["processes"])
    if not pids:
        launch_app(bind["command"])
        return

    windows = win32api.get_visible_windows_for_pids_cached(pids)
    if not windows:
        launch_app(bind["command"])
        return

    active = active_window_getter()
    current_index = find_index(windows, active)
    action, index = pick_next_action(len(windows), current_index)
    if action == "minimize":
        win32api.minimize_window(windows[index])
    else:
        win32api.restore_and_focus(windows[index])


def run_loop(config: dict[str, Any], config_path: Path | None = None) -> None:
    """Регистрирует все привязки плюс Alt+0 (меню-оверлей) и блокирующе
    ждёт нажатий (GetMessage — поток спит в ядре, не polling).
    Возврат — по WM_QUIT."""
    hotkey_map: dict[int, dict[str, Any]] = {}
    registered: list[int] = []
    hotkey_id = 1

    try:
        if win32api.register_hotkey(
            OVERLAY_HOTKEY_ID, win32api.MODIFIERS["alt"], OVERLAY_VK
        ):
            registered.append(OVERLAY_HOTKEY_ID)
        else:
            print(
                "Не удалось зарегистрировать Alt+0 (меню) — комбинация уже занята другой программой"
            )

        for number, bind in config.items():
            vk = 0x30 + int(number)  # VK_0..VK_9
            mods = 0
            for mod_name in bind["modifiers"]:
                mods |= win32api.MODIFIERS[mod_name]

            if win32api.register_hotkey(hotkey_id, mods, vk):
                hotkey_map[hotkey_id] = bind
                registered.append(hotkey_id)
            else:
                print(
                    f"Не удалось зарегистрировать привязку для {bind['name']} "
                    f"(комбинация уже занята другой программой)"
                )
            hotkey_id += 1

        if not registered:
            print("Не удалось зарегистрировать ни одной комбинации, выхожу.")
            return

        while True:
            result, msg = win32api.get_message()
            if result == 0:
                break
            if msg.message == win32api.WM_HOTKEY:
                if msg.wParam == OVERLAY_HOTKEY_ID:
                    open_overlay(config_path)
                else:
                    bind = hotkey_map.get(msg.wParam)
                    if bind is not None:
                        switch_to_app(bind)
            win32api.pump_message(msg)
    finally:
        for hid in registered:
            win32api.unregister_hotkey(hid)
