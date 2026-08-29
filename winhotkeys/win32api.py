"""Тонкие обёртки над WinAPI (ctypes): регистрация горячих клавиш,
поиск процессов по имени, перебор их окон, активация окна.

Никакой сторонней библиотеки (pywin32 и т.п.) — только user32.dll и
kernel32.dll напрямую через ctypes.
"""

from __future__ import annotations

import ctypes
import time
from collections.abc import Iterable
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---- Константы ------------------------------------------------------

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

MODIFIERS = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
}

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
SW_MINIMIZE = 6
SW_RESTORE = 9

TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * MAX_PATH),
    ]


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.RegisterHotKey.argtypes = [
    wintypes.HWND,
    ctypes.c_int,
    wintypes.UINT,
    wintypes.UINT,
]
user32.RegisterHotKey.restype = wintypes.BOOL

user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL

user32.GetMessageW.argtypes = [
    ctypes.POINTER(MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetMessageW.restype = ctypes.c_int

user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.TranslateMessage.restype = wintypes.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = ctypes.c_long

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL

user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD),
]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL

user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND

user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL

user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL

user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int

kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.Process32First.restype = wintypes.BOOL

kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.Process32Next.restype = wintypes.BOOL

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

DISCOVERY_CACHE_TTL_S = 0.2
_process_ids_cache: dict[tuple[int, frozenset[str]], tuple[float, set[int]]] = {}
_visible_windows_cache: dict[tuple[int, frozenset[int]], tuple[float, list]] = {}


# ---- Горячие клавиши и очередь сообщений -----------------------------


DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)


def make_process_dpi_aware() -> bool:
    """Помечает процесс per-monitor-v2 DPI aware. Без этого GetCursorPos/
    GetMonitorInfo/GetSystemMetrics отдают виртуализированные (уменьшенные
    под 96 DPI) координаты вместо физических пикселей — на масштабе,
    отличном от 100%, это ломает любую математику вроде "курсор у края
    монитора" (см. panel.py). Best-effort: на очень старых Windows атрибут
    недоступен, тогда просто не помечаем — не должно ронять вызывающего."""
    try:
        return bool(user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
    except (AttributeError, OSError):
        return False


def register_hotkey(hotkey_id: int, modifiers: int, vk: int) -> bool:
    return bool(user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, vk))


def unregister_hotkey(hotkey_id: int) -> None:
    user32.UnregisterHotKey(None, hotkey_id)


def get_message():
    """Блокирующий вызов GetMessage. Возвращает (result, msg).

    result == 0 означает WM_QUIT — цикл нужно завершить.
    Поток спит в ядре, пока не придёт сообщение — не polling, 0% CPU в простое.
    """
    msg = MSG()
    result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
    return result, msg


def pump_message(msg: MSG) -> None:
    user32.TranslateMessage(ctypes.byref(msg))
    user32.DispatchMessageW(ctypes.byref(msg))


# ---- Процессы и окна ---------------------------------------------------


def get_process_ids_by_name(names: Iterable[str]) -> set[int]:
    """PID всех запущенных процессов, чьё имя (с .exe или без) совпадает
    с одним из переданных имён (без учёта регистра)."""
    return set().union(*get_process_ids_by_names(names).values())


def get_process_ids_by_names(names: Iterable[str]) -> dict[str, set[int]]:
    """PID процессов по каждому имени из names одним снимком системы."""
    wanted = {name.lower() for name in names}
    result = {name: set() for name in wanted}

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot in (0, INVALID_HANDLE_VALUE):
        return result

    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        found = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while found:
            exe_name = entry.szExeFile.decode("mbcs", errors="ignore")
            stem = exe_name[:-4] if exe_name.lower().endswith(".exe") else exe_name
            if exe_name.lower() in wanted or stem.lower() in wanted:
                for name in (exe_name.lower(), stem.lower()):
                    if name in wanted:
                        result[name].add(entry.th32ProcessID)
            found = kernel32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)

    return result


def get_process_ids_by_name_cached(names: Iterable[str]) -> set[int]:
    key = (id(get_process_ids_by_name), frozenset(name.lower() for name in names))
    now = time.monotonic()
    cached = _process_ids_cache.get(key)
    if cached is not None and now - cached[0] < DISCOVERY_CACHE_TTL_S:
        return set(cached[1])

    result = get_process_ids_by_name(key[1])
    _process_ids_cache[key] = (now, result)
    return set(result)


def get_window_pid(hwnd) -> int:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_visible_windows_for_pids(pids: set[int]) -> list:
    """Видимые окна с непустым заголовком, принадлежащие одному из pids,
    в порядке, в котором их отдаёт система (Z-order сверху вниз)."""
    windows: list = []

    def callback(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        if get_window_pid(hwnd) in pids:
            windows.append(hwnd)
        return True

    proc = EnumWindowsProc(callback)
    user32.EnumWindows(proc, 0)
    return windows


def get_visible_windows_for_pids_cached(pids: set[int]) -> list:
    key = (id(get_visible_windows_for_pids), frozenset(pids))
    now = time.monotonic()
    cached = _visible_windows_cache.get(key)
    if cached is not None and now - cached[0] < DISCOVERY_CACHE_TTL_S:
        return list(cached[1])

    result = get_visible_windows_for_pids(set(key[1]))
    _visible_windows_cache[key] = (now, result)
    return list(result)


def clear_discovery_cache() -> None:
    _process_ids_cache.clear()
    _visible_windows_cache.clear()


def restore_and_focus(hwnd) -> None:
    """Разворачивает свёрнутое окно и выводит его на передний план.

    SetForegroundWindow часто молча отказывает, если вызывающий процесс
    не является текущим активным (foreground lock в Windows). Обходим это
    через AttachThreadInput — временно "одалживаем" вводной поток активного
    окна, как это делают стандартные переключатели окон.
    """
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    foreground = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(foreground, None)
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)

    attached_fg = attached_target = False
    if fg_thread and fg_thread != current_thread:
        attached_fg = bool(user32.AttachThreadInput(current_thread, fg_thread, True))
    if target_thread and target_thread != current_thread:
        attached_target = bool(
            user32.AttachThreadInput(current_thread, target_thread, True)
        )

    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached_fg:
            user32.AttachThreadInput(current_thread, fg_thread, False)
        if attached_target:
            user32.AttachThreadInput(current_thread, target_thread, False)


def minimize_window(hwnd) -> None:
    user32.ShowWindow(hwnd, SW_MINIMIZE)
