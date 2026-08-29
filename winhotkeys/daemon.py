"""Управление фоновым слушателем горячих клавиш: запуск, остановка,
статус, и сам цикл обработки сообщений."""

from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import win32api
from .core import find_index, pick_next_action

PID_FILE_NAME = "daemon.pid"
PANEL_PID_FILE_NAME = "panel.pid"

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Локальный UDP-порт, на котором (если запущена) слушает панель —
# уведомление "только что переключились на привязку N" по Alt+N, чтобы
# панель открылась и подсветила соответствующую иконку (см. panel.py).
# Обычный socket из стандартной библиотеки — daemon.py намеренно не
# зависит ни от одного стороннего GUI-пакета, чтобы Alt+1..9 работали,
# даже если PySide6/customtkinter не установлены.
PANEL_NOTIFY_PORT = 51823


def notify_panel_switch(number: str) -> None:
    """Best-effort уведомление панели о переключении по Alt+N. Ничего не
    делает, если панель не запущена/не слушает — это datagram на
    localhost, а не запрос, ответа не ждём и ошибку не считаем фатальной."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(number.encode("ascii"), ("127.0.0.1", PANEL_NOTIFY_PORT))
        finally:
            sock.close()
    except OSError:
        pass


def default_pid_path() -> Path:
    base = os.environ.get("APPDATA", str(Path.home()))
    return Path(base) / "winhotkeys" / PID_FILE_NAME


def default_panel_pid_path() -> Path:
    base = os.environ.get("APPDATA", str(Path.home()))
    return Path(base) / "winhotkeys" / PANEL_PID_FILE_NAME


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


# Формы причастий по родам — для status()/stop() с label="Панель" (ж.р.)
# наряду с дефолтным label="Слушатель" (м.р.), без дублирования сообщений.
_PARTICIPLES = {
    "m": {"running": "запущен", "was_running": "был запущен", "stopped": "остановлен"},
    "f": {"running": "запущена", "was_running": "была запущена", "stopped": "остановлена"},
}


def status(pid_path: Path, label: str = "Слушатель", gender: str = "m") -> str:
    forms = _PARTICIPLES[gender]
    pid = read_pid(pid_path)
    if pid is not None and _is_our_daemon(pid):
        return f"{label} {forms['running']} (PID {pid})"
    return f"{label} не {forms['running']}"


def stop(pid_path: Path, label: str = "Слушатель", gender: str = "m") -> str:
    forms = _PARTICIPLES[gender]
    pid = read_pid(pid_path)
    if pid is None or not is_process_running(pid):
        pid_path.unlink(missing_ok=True)
        return f"{label} не {forms['was_running']}"

    if not _is_our_daemon(pid):
        # PID из pid-файла Windows уже отдала другому процессу — настоящий
        # процесс, скорее всего, уже завершился сам. Не трогаем чужой процесс.
        pid_path.unlink(missing_ok=True)
        return (
            f"{label} не {forms['was_running']} (PID {pid} в pid-файле уже "
            "принадлежит другому процессу, вероятно завершился сам)"
        )

    try:
        os.kill(pid, 15)  # на Windows Python транслирует это в TerminateProcess
    except OSError as exc:
        pid_path.unlink(missing_ok=True)
        return f"Не удалось остановить процесс PID {pid} ({exc}); pid-файл очищен"

    pid_path.unlink(missing_ok=True)
    return f"{label} (PID {pid}) {forms['stopped']}"


def _spawn_background_service(
    pid_path: Path, config_path: Path, subcommand: str, label: str, started_word: str
) -> str:
    """Общий boilerplate запуска фонового сервиса (демон хоткеев или
    резидентная панель): не плодит второй процесс, если наш уже запущен
    (pid-файл + _is_our_daemon), иначе спавнит `run.py <subcommand>` без
    консольного окна и запоминает PID."""
    existing = read_pid(pid_path)
    if existing is not None and _is_our_daemon(existing):
        return f"{label} уже {started_word} (PID {existing})"

    entry_script = Path(__file__).resolve().parent.parent / "run.py"
    creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    proc = subprocess.Popen(
        [sys.executable, str(entry_script), subcommand, "--config", str(config_path)],
        creationflags=creationflags,
        close_fds=True,
    )

    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(proc.pid))
    return f"{label} {started_word} в фоне (PID {proc.pid})"


def start_background(pid_path: Path, config_path: Path) -> str:
    """Включение: поднимает слушатель горячих клавиш (Alt+1..9) в отдельном
    фоновом процессе."""
    return _spawn_background_service(pid_path, config_path, "run", "Слушатель", "запущен")


def start_panel_background(pid_path: Path, config_path: Path) -> str:
    """Включение: поднимает резидентную боковую панель в отдельном фоновом
    процессе — один раз при старте, а не заново при каждом открытии."""
    return _spawn_background_service(pid_path, config_path, "panel", "Панель", "запущена")


def launch_app(command: str) -> None:
    subprocess.Popen(command, shell=True)


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


def run_loop(config: dict[str, Any]) -> None:
    """Регистрирует все привязки (Alt+1..9) и блокирующе ждёт нажатий
    (GetMessage — поток спит в ядре, не polling). Возврат — по WM_QUIT.

    config — плоский словарь биндов (cfg["binds"], не весь конфиг с
    настройками панели)."""
    hotkey_map: dict[int, tuple[str, dict[str, Any]]] = {}
    registered: list[int] = []
    hotkey_id = 1

    try:
        for number, bind in config.items():
            vk = 0x30 + int(number)  # VK_0..VK_9
            mods = 0
            for mod_name in bind["modifiers"]:
                mods |= win32api.MODIFIERS[mod_name]

            if win32api.register_hotkey(hotkey_id, mods, vk):
                hotkey_map[hotkey_id] = (number, bind)
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
                entry = hotkey_map.get(msg.wParam)
                if entry is not None:
                    number, bind = entry
                    switch_to_app(bind)
                    notify_panel_switch(number)
            win32api.pump_message(msg)
    finally:
        for hid in registered:
            win32api.unregister_hotkey(hid)
