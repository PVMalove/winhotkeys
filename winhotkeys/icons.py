"""Извлечение иконки .exe в формате PPM (для tkinter.PhotoImage) —
без Pillow и других сторонних библиотек, только ctypes поверх GDI/shell32.
"""

from __future__ import annotations

import ctypes
import shlex
import shutil
from collections.abc import Iterable
from ctypes import wintypes
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import win32api

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DIB_RGB_COLORS = 0
BI_RGB = 0


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", ctypes.c_long),
        ("bmWidth", ctypes.c_long),
        ("bmHeight", ctypes.c_long),
        ("bmWidthBytes", ctypes.c_long),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 1),
    ]


shell32.ExtractIconExW.argtypes = [
    wintypes.LPCWSTR,
    ctypes.c_int,
    ctypes.POINTER(wintypes.HICON),
    ctypes.POINTER(wintypes.HICON),
    wintypes.UINT,
]
shell32.ExtractIconExW.restype = wintypes.UINT

user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(ICONINFO)]
user32.GetIconInfo.restype = wintypes.BOOL

user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.DestroyIcon.restype = wintypes.BOOL

gdi32.GetObjectW.argtypes = [wintypes.HGDIOBJ, ctypes.c_int, ctypes.c_void_p]
gdi32.GetObjectW.restype = ctypes.c_int

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC

gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL

gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ

gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int

gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


def _first_token(command: str) -> str | None:
    """Первый токен команды запуска (сам путь/имя exe, без аргументов)."""
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        parts = command.split()
    if not parts:
        return None
    return parts[0].strip('"')


def resolve_exe_path(command: str) -> str | None:
    """Путь к исполняемому файлу из строки команды (учитывает PATH/PATHEXT).

    Для команд вроде "code" реальный файл на PATH нередко является .cmd/.bat
    обёрткой — тогда иконка получится не самая красивая (см. README).
    """
    token = _first_token(command)
    if not token:
        return None
    path = Path(token)
    if path.is_absolute() and path.exists():
        return str(path)
    return shutil.which(token)


def get_process_image_path(pid: int) -> str | None:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf_len = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(260)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(buf_len)):
            return buf.value
        return None
    finally:
        kernel32.CloseHandle(handle)


def resolve_icon_source(bind: dict[str, Any]) -> str | None:
    """Путь к exe для извлечения иконки: сперва пробуем реально запущенный
    процесс (самый точный источник), иначе — команду запуска из привязки."""
    pids = win32api.get_process_ids_by_name(bind["processes"])
    for pid in pids:
        path = get_process_image_path(pid)
        if path:
            return path
    return resolve_exe_path(bind["command"])


def resolve_icon_sources(bindings: Iterable[dict[str, Any]]) -> dict[int, str | None]:
    """Resolve all icon sources with one process snapshot."""
    bindings = list(bindings)
    all_process_names = {name for bind in bindings for name in bind["processes"]}
    pids_by_name = win32api.get_process_ids_by_names(all_process_names)
    sources: dict[int, str | None] = {}

    for bind in bindings:
        matching_pids = {
            pid
            for name in bind["processes"]
            for pid in pids_by_name.get(name.lower(), set())
        }
        source = next((get_process_image_path(pid) for pid in matching_pids), None)
        sources[id(bind)] = source or resolve_exe_path(bind["command"])
    return sources


@lru_cache(maxsize=128)
def _get_bgra_buffer(exe_path: str):
    """Сырые пиксели первой иконки exe как (buffer, width, height) в формате
    top-down 32bpp BGRA, либо None. Общая часть для PPM- и PIL-путей ниже."""
    large = wintypes.HICON()
    small = wintypes.HICON()
    count = shell32.ExtractIconExW(
        exe_path, 0, ctypes.byref(large), ctypes.byref(small), 1
    )
    if small.value and small.value != large.value:
        user32.DestroyIcon(small)
    if count == 0 or not large.value:
        return None

    hicon = large
    try:
        info = ICONINFO()
        if not user32.GetIconInfo(hicon, ctypes.byref(info)):
            return None
        try:
            bmp = BITMAP()
            if (
                gdi32.GetObjectW(
                    info.hbmColor, ctypes.sizeof(BITMAP), ctypes.byref(bmp)
                )
                == 0
            ):
                return None

            width, height = bmp.bmWidth, bmp.bmHeight
            if width <= 0 or height <= 0:
                return None

            buffer = (ctypes.c_ubyte * (width * height * 4))()

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height  # отрицательная высота = top-down DIB
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = BI_RGB

            hdc = gdi32.CreateCompatibleDC(None)
            if not hdc:
                return None
            try:
                got = gdi32.GetDIBits(
                    hdc,
                    info.hbmColor,
                    0,
                    height,
                    buffer,
                    ctypes.byref(bmi),
                    DIB_RGB_COLORS,
                )
                if got == 0:
                    return None
            finally:
                gdi32.DeleteDC(hdc)

            return bytes(buffer), width, height
        finally:
            gdi32.DeleteObject(info.hbmColor)
            if info.hbmMask:
                gdi32.DeleteObject(info.hbmMask)
    finally:
        user32.DestroyIcon(hicon)


def extract_icon_ppm(
    exe_path: str, background: tuple[int, int, int] = (45, 45, 48)
) -> bytes | None:
    """Иконка exe в виде байтов PPM (P6) — формат, который tkinter.PhotoImage
    понимает напрямую через data=, без временных файлов и без Pillow.

    PPM не хранит альфа-канал, поэтому прозрачность заранее вплавляется в
    background (плоский цвет). Для полупрозрачного/размытого фона (оверлей)
    используйте extract_icon_image — она сохраняет альфа-канал.
    """
    result = _get_bgra_buffer(exe_path)
    if result is None:
        return None
    buffer, width, height = result
    return _compose_ppm(buffer, width, height, background)


def extract_icon_image(exe_path: str):
    """Иконка exe как PIL.Image (RGBA, с сохранённым альфа-каналом) — для
    оверлея, где Pillow уже установлен вместе с customtkinter. Возвращает
    None, если Pillow недоступен или иконку извлечь не удалось."""
    try:
        from PIL import Image
    except ImportError:
        return None

    result = _get_bgra_buffer(exe_path)
    if result is None:
        return None
    buffer, width, height = result
    return Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).copy()


def _compose_ppm(
    buffer, width: int, height: int, background: tuple[int, int, int]
) -> bytes:
    """Альфа-смешивание BGRA -> RGB поверх фона и упаковка в PPM (P6)."""
    bg_r, bg_g, bg_b = background
    pixels = bytearray(width * height * 3)
    for i in range(width * height):
        b, g, r, a = (
            buffer[i * 4],
            buffer[i * 4 + 1],
            buffer[i * 4 + 2],
            buffer[i * 4 + 3],
        )
        if a == 255:
            out = (r, g, b)
        elif a == 0:
            out = (bg_r, bg_g, bg_b)
        else:
            out = (
                (r * a + bg_r * (255 - a)) // 255,
                (g * a + bg_g * (255 - a)) // 255,
                (b * a + bg_b * (255 - a)) // 255,
            )
        pixels[i * 3 : i * 3 + 3] = bytes(out)

    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    return header + bytes(pixels)


def get_icon_ppm(
    bind: dict[str, Any], background: tuple[int, int, int] = (45, 45, 48)
) -> bytes | None:
    """Иконка для привязки как PPM, либо None — тогда UI показывает
    цветную заглушку с первой буквой имени. Ошибки WinAPI/ФС не должны
    ронять оверлей, поэтому здесь широкий except."""
    try:
        path = resolve_icon_source(bind)
        if not path:
            return None
        return extract_icon_ppm(path, background)
    except Exception:
        return None


def get_icon_image(bind: dict[str, Any], source_path: str | None = None):
    """Иконка для привязки как PIL.Image (RGBA), либо None. Как get_icon_ppm,
    но с сохранённым альфа-каналом — для оверлея на customtkinter."""
    try:
        path = source_path or resolve_icon_source(bind)
        if not path:
            return None
        return extract_icon_image(path)
    except Exception:
        return None
