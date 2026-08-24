import shutil

import pytest

from winhotkeys import icons


def test_first_token_simple_command():
    assert icons._first_token("code") == "code"


def test_first_token_with_arguments():
    assert icons._first_token('wt.exe -p "PowerShell"') == "wt.exe"


def test_first_token_quoted_path_with_spaces():
    assert icons._first_token(r'"C:\Program Files\App\app.exe" --flag') == r"C:\Program Files\App\app.exe"


def test_first_token_empty_command():
    assert icons._first_token("") is None


def test_resolve_exe_path_uses_which(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda token: r"C:\fake\pwsh.exe" if token == "pwsh" else None)
    assert icons.resolve_exe_path("pwsh -NoLogo") == r"C:\fake\pwsh.exe"


def test_resolve_exe_path_returns_none_when_not_found(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda token: None)
    assert icons.resolve_exe_path("does-not-exist") is None


def test_resolve_icon_source_prefers_running_process(monkeypatch):
    from winhotkeys import win32api

    monkeypatch.setattr(win32api, "get_process_ids_by_name", lambda names: {123})
    monkeypatch.setattr(icons, "get_process_image_path", lambda pid: r"C:\real\Code.exe" if pid == 123 else None)

    bind = {"name": "VS Code", "command": "code", "processes": ["Code"], "modifiers": ["alt"]}
    assert icons.resolve_icon_source(bind) == r"C:\real\Code.exe"


def test_resolve_icon_source_falls_back_to_command_when_not_running(monkeypatch):
    from winhotkeys import win32api

    monkeypatch.setattr(win32api, "get_process_ids_by_name", lambda names: set())
    monkeypatch.setattr(icons, "resolve_exe_path", lambda command: r"C:\fallback\code.cmd")

    bind = {"name": "VS Code", "command": "code", "processes": ["Code"], "modifiers": ["alt"]}
    assert icons.resolve_icon_source(bind) == r"C:\fallback\code.cmd"


def test_get_icon_ppm_returns_none_on_missing_source(monkeypatch):
    monkeypatch.setattr(icons, "resolve_icon_source", lambda bind: None)
    bind = {"name": "X", "command": "x", "processes": ["x"], "modifiers": ["alt"]}
    assert icons.get_icon_ppm(bind) is None


def test_get_icon_ppm_never_raises_on_unexpected_errors(monkeypatch):
    def boom(bind):
        raise RuntimeError("что-то сломалось в WinAPI")

    monkeypatch.setattr(icons, "resolve_icon_source", boom)
    bind = {"name": "X", "command": "x", "processes": ["x"], "modifiers": ["alt"]}
    assert icons.get_icon_ppm(bind) is None


def test_extract_icon_ppm_for_a_real_system_executable():
    """Санити-проверка реального извлечения иконки через WinAPI/GDI —
    без открытия какого-либо окна, только байты PPM."""
    notepad = shutil.which("notepad")
    if not notepad:
        pytest.skip("notepad.exe не найден в PATH — пропускаем санити-проверку WinAPI")

    ppm = icons.extract_icon_ppm(notepad)

    assert ppm is not None
    assert ppm.startswith(b"P6\n")
    header, _, pixels = ppm.partition(b"255\n")
    width, height = map(int, header.split(b"\n")[1].split(b" "))
    assert len(pixels) == width * height * 3


def test_extract_icon_image_for_a_real_system_executable():
    """Как test_extract_icon_ppm_for_a_real_system_executable, но для
    PIL-варианта (используется оверлеем) — проверяет сохранённый альфа-канал."""
    pytest.importorskip("PIL")
    notepad = shutil.which("notepad")
    if not notepad:
        pytest.skip("notepad.exe не найден в PATH — пропускаем санити-проверку WinAPI")

    img = icons.extract_icon_image(notepad)

    assert img is not None
    assert img.mode == "RGBA"
    assert img.size[0] > 0 and img.size[1] > 0
    # хотя бы часть пикселей должна быть непрозрачной — иначе извлечение сломано
    alpha_bytes = img.tobytes()[3::4]
    assert any(a > 0 for a in alpha_bytes)
