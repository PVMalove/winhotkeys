import types

from winhotkeys import daemon, win32api


def make_msg(message, wparam=0):
    return types.SimpleNamespace(message=message, wParam=wparam)


def test_switch_to_app_launches_when_process_not_running(monkeypatch):
    monkeypatch.setattr(win32api, "get_process_ids_by_name", lambda names: set())
    launched = {}
    monkeypatch.setattr(daemon, "launch_app", lambda cmd: launched.setdefault("cmd", cmd))

    bind = {"name": "X", "command": "x.exe", "processes": ["x"], "modifiers": ["alt"]}
    daemon.switch_to_app(bind, active_window_getter=lambda: 0)

    assert launched["cmd"] == "x.exe"


def test_switch_to_app_launches_when_no_visible_window(monkeypatch):
    monkeypatch.setattr(win32api, "get_process_ids_by_name", lambda names: {111})
    monkeypatch.setattr(win32api, "get_visible_windows_for_pids", lambda pids: [])
    launched = {}
    monkeypatch.setattr(daemon, "launch_app", lambda cmd: launched.setdefault("cmd", cmd))

    bind = {"name": "X", "command": "x.exe", "processes": ["x"], "modifiers": ["alt"]}
    daemon.switch_to_app(bind, active_window_getter=lambda: 0)

    assert launched["cmd"] == "x.exe"


def test_switch_to_app_focuses_next_window(monkeypatch):
    monkeypatch.setattr(win32api, "get_process_ids_by_name", lambda names: {111})
    monkeypatch.setattr(win32api, "get_visible_windows_for_pids", lambda pids: [1, 2, 3])
    focused = {}
    monkeypatch.setattr(win32api, "restore_and_focus", lambda hwnd: focused.setdefault("hwnd", hwnd))

    bind = {"name": "X", "command": "x.exe", "processes": ["x"], "modifiers": ["alt"]}
    daemon.switch_to_app(bind, active_window_getter=lambda: 2)  # активно окно #2 (index 1)

    assert focused["hwnd"] == 3  # переключились на следующее


def test_switch_to_app_minimizes_last_window_instead_of_wrapping(monkeypatch):
    monkeypatch.setattr(win32api, "get_process_ids_by_name", lambda names: {111})
    monkeypatch.setattr(win32api, "get_visible_windows_for_pids", lambda pids: [1, 2, 3])
    minimized = {}
    monkeypatch.setattr(win32api, "minimize_window", lambda hwnd: minimized.setdefault("hwnd", hwnd))

    bind = {"name": "X", "command": "x.exe", "processes": ["x"], "modifiers": ["alt"]}
    daemon.switch_to_app(bind, active_window_getter=lambda: 3)  # последнее окно активно, пролистали все

    assert minimized["hwnd"] == 3


def test_switch_to_app_toggles_single_window_between_focus_and_minimize(monkeypatch):
    monkeypatch.setattr(win32api, "get_process_ids_by_name", lambda names: {111})
    monkeypatch.setattr(win32api, "get_visible_windows_for_pids", lambda pids: [1])
    minimized = {}
    monkeypatch.setattr(win32api, "minimize_window", lambda hwnd: minimized.setdefault("hwnd", hwnd))

    bind = {"name": "X", "command": "x.exe", "processes": ["x"], "modifiers": ["alt"]}
    daemon.switch_to_app(bind, active_window_getter=lambda: 1)  # единственное окно уже активно

    assert minimized["hwnd"] == 1


def test_switch_to_app_focuses_single_window_when_not_active(monkeypatch):
    monkeypatch.setattr(win32api, "get_process_ids_by_name", lambda names: {111})
    monkeypatch.setattr(win32api, "get_visible_windows_for_pids", lambda pids: [1])
    focused = {}
    monkeypatch.setattr(win32api, "restore_and_focus", lambda hwnd: focused.setdefault("hwnd", hwnd))

    bind = {"name": "X", "command": "x.exe", "processes": ["x"], "modifiers": ["alt"]}
    daemon.switch_to_app(bind, active_window_getter=lambda: 999)  # фокус в другой программе

    assert focused["hwnd"] == 1


def test_run_loop_dispatches_hotkey_to_correct_bind(monkeypatch):
    monkeypatch.setattr(win32api, "register_hotkey", lambda *a, **k: True)
    monkeypatch.setattr(win32api, "unregister_hotkey", lambda *a, **k: None)
    monkeypatch.setattr(win32api, "pump_message", lambda msg: None)

    messages = [
        (1, make_msg(win32api.WM_HOTKEY, wparam=2)),
        (0, make_msg(win32api.WM_QUIT)),
    ]
    monkeypatch.setattr(win32api, "get_message", lambda: messages.pop(0))

    called = {}
    monkeypatch.setattr(daemon, "switch_to_app", lambda bind, **k: called.setdefault("bind", bind))

    config = {
        "1": {"name": "VS Code", "command": "code", "processes": ["Code"], "modifiers": ["alt"]},
        "2": {"name": "PowerShell 7", "command": "pwsh", "processes": ["pwsh"], "modifiers": ["alt"]},
    }
    daemon.run_loop(config)

    assert called["bind"]["name"] == "PowerShell 7"


def test_run_loop_unregisters_hotkeys_on_exit(monkeypatch):
    monkeypatch.setattr(win32api, "register_hotkey", lambda *a, **k: True)
    unregistered = []
    monkeypatch.setattr(win32api, "unregister_hotkey", lambda hid: unregistered.append(hid))
    monkeypatch.setattr(win32api, "pump_message", lambda msg: None)
    monkeypatch.setattr(win32api, "get_message", lambda: (0, make_msg(win32api.WM_QUIT)))

    config = {"1": {"name": "VS Code", "command": "code", "processes": ["Code"], "modifiers": ["alt"]}}
    daemon.run_loop(config)

    assert unregistered == [1]  # только привязка "1" — Alt+0 сюда больше не входит


def test_stop_when_not_running_cleans_up_stale_pid_file(tmp_path, monkeypatch):
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("999999")
    monkeypatch.setattr(daemon, "is_process_running", lambda pid: False)

    result = daemon.stop(pid_path)

    assert "не был запущен" in result
    assert not pid_path.exists()


def test_stop_when_running_kills_and_removes_pid_file(tmp_path, monkeypatch):
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("4242")
    monkeypatch.setattr(daemon, "is_process_running", lambda pid: True)
    monkeypatch.setattr(daemon, "_is_our_daemon", lambda pid: True)
    killed = {}
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: killed.setdefault("pid", pid))

    result = daemon.stop(pid_path)

    assert killed["pid"] == 4242
    assert "остановлен" in result
    assert not pid_path.exists()


def test_stop_when_pid_reused_by_other_process_does_not_kill_it(tmp_path, monkeypatch):
    """Регрессия: если Windows успела переиспользовать PID из pid-файла под
    посторонний процесс (например, наш демон погиб раньше, чем ожидалось),
    stop() не должен пытаться его завершать — раньше это падало
    PermissionError, а в худшем случае могло прибить чужой процесс."""
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("4242")
    monkeypatch.setattr(daemon, "is_process_running", lambda pid: True)
    monkeypatch.setattr(daemon, "_is_our_daemon", lambda pid: False)

    def fail_kill(*a, **k):
        raise AssertionError("os.kill не должен вызываться для чужого процесса")

    monkeypatch.setattr(daemon.os, "kill", fail_kill)

    result = daemon.stop(pid_path)

    assert "не был запущен" in result
    assert not pid_path.exists()


def test_stop_handles_permission_error_from_kill_gracefully(tmp_path, monkeypatch):
    """Регрессия: os.kill может кинуть PermissionError даже когда PID
    похож на наш процесс (например, из-за несовпадения уровня целостности
    процесса) — раньше это падало необработанным исключением наружу."""
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("4242")
    monkeypatch.setattr(daemon, "is_process_running", lambda pid: True)
    monkeypatch.setattr(daemon, "_is_our_daemon", lambda pid: True)

    def raise_permission_error(*a, **k):
        raise PermissionError("[WinError 5] Отказано в доступе")

    monkeypatch.setattr(daemon.os, "kill", raise_permission_error)

    result = daemon.stop(pid_path)

    assert "Не удалось остановить" in result
    assert not pid_path.exists()


def test_start_background_skips_when_already_running(tmp_path, monkeypatch):
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("123")
    monkeypatch.setattr(daemon, "_is_our_daemon", lambda pid: True)

    def fail_popen(*a, **k):
        raise AssertionError("Popen не должен вызываться, если слушатель уже запущен")

    monkeypatch.setattr(daemon.subprocess, "Popen", fail_popen)

    result = daemon.start_background(pid_path, tmp_path / "config.json")

    assert "уже запущен" in result


def test_start_background_launches_when_pid_reused_by_other_process(tmp_path, monkeypatch):
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("123")
    monkeypatch.setattr(daemon, "_is_our_daemon", lambda pid: False)

    class FakeProc:
        pid = 555

    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: FakeProc())

    result = daemon.start_background(pid_path, tmp_path / "config.json")

    assert "запущен в фоне" in result
    assert pid_path.read_text() == "555"


def test_start_panel_background_skips_when_already_running(tmp_path, monkeypatch):
    pid_path = tmp_path / "panel.pid"
    pid_path.write_text("123")
    monkeypatch.setattr(daemon, "_is_our_daemon", lambda pid: True)

    def fail_popen(*a, **k):
        raise AssertionError("Popen не должен вызываться, если панель уже запущена")

    monkeypatch.setattr(daemon.subprocess, "Popen", fail_popen)

    result = daemon.start_panel_background(pid_path, tmp_path / "config.json")

    assert "уже запущена" in result


def test_start_panel_background_launches_and_writes_pid(tmp_path, monkeypatch):
    pid_path = tmp_path / "panel.pid"
    monkeypatch.setattr(daemon, "_is_our_daemon", lambda pid: False)

    class FakeProc:
        pid = 777

    captured = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        return FakeProc()

    monkeypatch.setattr(daemon.subprocess, "Popen", fake_popen)

    result = daemon.start_panel_background(pid_path, tmp_path / "config.json")

    assert "запущена в фоне" in result
    assert pid_path.read_text() == "777"
    assert captured["argv"][2] == "panel"  # спавнит именно служебную команду panel, не run


def test_default_panel_pid_path_differs_from_daemon(monkeypatch):
    monkeypatch.setenv("APPDATA", r"C:\fake")
    assert daemon.default_panel_pid_path().name == "panel.pid"
    assert daemon.default_panel_pid_path() != daemon.default_pid_path()


def test_is_our_daemon_matches_by_python_executable_name(monkeypatch):
    from winhotkeys import icons

    monkeypatch.setattr(daemon, "is_process_running", lambda pid: True)
    monkeypatch.setattr(
        icons, "get_process_image_path", lambda pid: daemon.sys.executable.upper()
    )

    assert daemon._is_our_daemon(4242) is True


def test_is_our_daemon_rejects_unrelated_process(monkeypatch):
    from winhotkeys import icons

    monkeypatch.setattr(daemon, "is_process_running", lambda pid: True)
    monkeypatch.setattr(icons, "get_process_image_path", lambda pid: r"C:\Windows\explorer.exe")

    assert daemon._is_our_daemon(4242) is False


def test_is_our_daemon_false_when_process_not_running(monkeypatch):
    monkeypatch.setattr(daemon, "is_process_running", lambda pid: False)

    assert daemon._is_our_daemon(4242) is False


def test_status_reports_not_running_without_pid_file(tmp_path):
    assert "не запущен" in daemon.status(tmp_path / "daemon.pid")
