import pytest

from winhotkeys import config


def test_default_config_has_expected_binds():
    cfg = config.default_config()
    assert cfg["1"]["name"] == "VS Code"
    assert cfg["2"]["processes"] == ["WindowsTerminal", "pwsh"]


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "cfg.json"
    cfg = config.default_config()
    config.save_config(path, cfg)
    assert config.load_config(path) == cfg


def test_load_missing_file_returns_default(tmp_path):
    path = tmp_path / "missing.json"
    assert config.load_config(path) == config.default_config()


def test_add_bind_appends_new_entry_without_mutating_input():
    cfg = {}
    new_cfg = config.add_bind(cfg, "3", "Telegram", "Telegram.exe", ["Telegram"], ["alt"])
    assert new_cfg["3"]["name"] == "Telegram"
    assert cfg == {}


def test_add_bind_rejects_out_of_range_number():
    with pytest.raises(ValueError):
        config.add_bind({}, "10", "X", "x.exe", ["X"], ["alt"])


def test_add_bind_rejects_zero_reserved_for_overlay():
    with pytest.raises(ValueError):
        config.add_bind({}, "0", "X", "x.exe", ["X"], ["alt"])


def test_add_bind_rejects_unknown_modifier():
    with pytest.raises(ValueError):
        config.add_bind({}, "3", "X", "x.exe", ["X"], ["meta"])


def test_add_bind_rejects_empty_processes():
    with pytest.raises(ValueError):
        config.add_bind({}, "3", "X", "x.exe", [], ["alt"])


def test_add_bind_rejects_empty_name():
    with pytest.raises(ValueError):
        config.add_bind({}, "3", "  ", "x.exe", ["X"], ["alt"])


def test_remove_bind_does_not_mutate_input():
    cfg = config.default_config()
    new_cfg = config.remove_bind(cfg, "1")
    assert "1" not in new_cfg
    assert "1" in cfg


def test_remove_missing_bind_raises():
    with pytest.raises(KeyError):
        config.remove_bind({}, "5")
