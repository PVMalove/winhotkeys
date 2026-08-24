import argparse
import os

import pytest

from winhotkeys import cli, config as config_mod, daemon


def _args(config_path):
    return argparse.Namespace(config=str(config_path))


def test_cmd_overlay_cleans_up_own_pid_file_on_exit(tmp_path, monkeypatch):
    """Регрессия: раньше pid-файл оверлея не удалялся после выхода, и если
    Windows позже переиспользовала тот же PID для другого процесса,
    is_process_running ошибочно считала оверлей всё ещё открытым — Alt+0
    переставал открывать окно навсегда после первого же выбора программы."""
    pytest.importorskip("customtkinter")
    from winhotkeys import overlay as overlay_module

    pid_path = tmp_path / "overlay.pid"
    monkeypatch.setattr(daemon, "default_overlay_pid_path", lambda: pid_path)

    def fake_show(cfg):
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()))

    monkeypatch.setattr(overlay_module, "show", fake_show)

    config_path = tmp_path / "config.json"
    config_mod.save_config(config_path, config_mod.default_config())

    result = cli.cmd_overlay(_args(config_path))

    assert result == 0
    assert not pid_path.exists()


def test_cmd_overlay_does_not_delete_pid_file_of_another_process(tmp_path, monkeypatch):
    """Если pid-файл успели перезаписать другим PID (например, новый оверлей
    уже запустился), наш выходящий процесс не должен его затирать."""
    pytest.importorskip("customtkinter")
    from winhotkeys import overlay as overlay_module

    pid_path = tmp_path / "overlay.pid"
    monkeypatch.setattr(daemon, "default_overlay_pid_path", lambda: pid_path)

    def fake_show(cfg):
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid() + 1))

    monkeypatch.setattr(overlay_module, "show", fake_show)

    config_path = tmp_path / "config.json"
    config_mod.save_config(config_path, config_mod.default_config())

    cli.cmd_overlay(_args(config_path))

    assert pid_path.exists()
