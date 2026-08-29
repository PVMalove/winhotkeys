import argparse

from winhotkeys import cli, config as config_mod, daemon


def _args(config_path, **extra):
    return argparse.Namespace(config=str(config_path), **extra)


def test_cmd_start_background_starts_daemon_and_panel(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "config.json"
    config_mod.save_config(config_path, config_mod.default_config())

    calls = []
    monkeypatch.setattr(
        daemon,
        "start_background",
        lambda pid_path, cfg_path: calls.append(("daemon", pid_path, cfg_path)) or "Слушатель запущен в фоне (PID 1)",
    )
    monkeypatch.setattr(
        daemon,
        "start_panel_background",
        lambda pid_path, cfg_path: calls.append(("panel", pid_path, cfg_path)) or "Панель запущена в фоне (PID 2)",
    )

    result = cli.cmd_start(_args(config_path, foreground=False))

    assert result == 0
    assert [c[0] for c in calls] == ["daemon", "panel"]
    out = capsys.readouterr().out
    assert "Слушатель запущен" in out
    assert "Панель запущена" in out


def test_cmd_start_foreground_runs_daemon_only_with_binds(tmp_path, monkeypatch):
    """--foreground остаётся отладочным режимом только слушателя (Alt+1..9)
    — панель им не затрагивается, и run_loop получает именно cfg["binds"],
    а не весь конфиг с настройками панели."""
    config_path = tmp_path / "config.json"
    config_mod.save_config(config_path, config_mod.default_config())

    def fail_panel(*a, **k):
        raise AssertionError("панель не должна стартовать в --foreground")

    monkeypatch.setattr(daemon, "start_panel_background", fail_panel)

    called = {}
    monkeypatch.setattr(daemon, "run_loop", lambda binds: called.setdefault("binds", binds))

    result = cli.cmd_start(_args(config_path, foreground=True))

    assert result == 0
    assert "1" in called["binds"]
    assert "panel" not in called["binds"]


def test_cmd_stop_stops_daemon_and_panel(monkeypatch):
    calls = []
    monkeypatch.setattr(
        daemon,
        "stop",
        lambda pid_path, label="Слушатель", gender="m": calls.append((label, gender)) or f"{label} остановлен",
    )

    result = cli.cmd_stop(argparse.Namespace())

    assert result == 0
    assert calls == [("Слушатель", "m"), ("Панель", "f")]


def test_cmd_status_reports_daemon_and_panel(monkeypatch):
    calls = []
    monkeypatch.setattr(
        daemon,
        "status",
        lambda pid_path, label="Слушатель", gender="m": calls.append((label, gender)) or f"{label} запущен",
    )

    result = cli.cmd_status(argparse.Namespace())

    assert result == 0
    assert calls == [("Слушатель", "m"), ("Панель", "f")]


def test_cmd_add_stores_new_bind_under_binds_key(tmp_path):
    config_path = tmp_path / "config.json"
    config_mod.save_config(config_path, config_mod.default_config())

    args = _args(
        config_path,
        number="3",
        name="Telegram",
        command="Telegram.exe",
        process=["Telegram"],
        mod=None,
    )
    result = cli.cmd_add(args)

    assert result == 0
    cfg = config_mod.load_config(config_path)
    assert cfg["binds"]["3"]["name"] == "Telegram"
    assert cfg["panel"] == config_mod.default_panel_settings()


def test_cmd_remove_deletes_bind_under_binds_key(tmp_path):
    config_path = tmp_path / "config.json"
    config_mod.save_config(config_path, config_mod.default_config())

    result = cli.cmd_remove(_args(config_path, number="1"))

    assert result == 0
    cfg = config_mod.load_config(config_path)
    assert "1" not in cfg["binds"]


def test_cmd_list_reads_binds_key(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_mod.save_config(config_path, config_mod.default_config())

    result = cli.cmd_list(_args(config_path))

    assert result == 0
    assert "VS Code" in capsys.readouterr().out
