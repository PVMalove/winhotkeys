from winhotkeys import win32api


def test_get_visible_windows_for_pids_filters_by_visibility_title_and_pid(monkeypatch):
    fake_windows = {
        1: {"visible": True, "has_title": True, "pid": 100},   # подходит
        2: {"visible": False, "has_title": True, "pid": 100},  # невидимое
        3: {"visible": True, "has_title": False, "pid": 100},  # без заголовка
        4: {"visible": True, "has_title": True, "pid": 200},   # чужой процесс
        5: {"visible": True, "has_title": True, "pid": 100},   # подходит
    }

    def fake_enum_windows(proc, lparam):
        for hwnd in fake_windows:
            proc(hwnd, lparam)
        return True

    monkeypatch.setattr(win32api.user32, "EnumWindows", fake_enum_windows)
    monkeypatch.setattr(win32api.user32, "IsWindowVisible", lambda h: fake_windows[h]["visible"])
    monkeypatch.setattr(
        win32api.user32, "GetWindowTextLengthW", lambda h: 1 if fake_windows[h]["has_title"] else 0
    )
    monkeypatch.setattr(win32api, "get_window_pid", lambda h: fake_windows[h]["pid"])

    result = win32api.get_visible_windows_for_pids({100})

    assert result == [1, 5]


def test_get_visible_windows_for_pids_returns_empty_when_no_match(monkeypatch):
    monkeypatch.setattr(win32api.user32, "EnumWindows", lambda proc, lparam: True)

    result = win32api.get_visible_windows_for_pids({100})

    assert result == []


def test_make_process_dpi_aware_calls_winapi_and_reports_success(monkeypatch):
    monkeypatch.setattr(win32api.user32, "SetProcessDpiAwarenessContext", lambda ctx: 1)

    assert win32api.make_process_dpi_aware() is True


def test_make_process_dpi_aware_reports_failure_without_raising(monkeypatch):
    monkeypatch.setattr(win32api.user32, "SetProcessDpiAwarenessContext", lambda ctx: 0)

    assert win32api.make_process_dpi_aware() is False


def test_make_process_dpi_aware_survives_missing_winapi_on_old_windows(monkeypatch):
    def raise_missing(ctx):
        raise AttributeError("SetProcessDpiAwarenessContext")

    monkeypatch.setattr(win32api.user32, "SetProcessDpiAwarenessContext", raise_missing)

    assert win32api.make_process_dpi_aware() is False
