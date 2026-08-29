import json

import pytest

from winhotkeys import config


def test_default_config_has_expected_binds():
    cfg = config.default_config()
    assert cfg["binds"]["1"]["name"] == "VS Code"
    assert cfg["binds"]["2"]["processes"] == ["WindowsTerminal", "pwsh"]


def test_default_config_has_expected_panel_settings():
    cfg = config.default_config()
    assert cfg["panel"] == {
        "trigger": "edge-slide",
        "side": "right",
        "hide_delay": 3,
        "icon_spacing": 6,
        "edge_offset": 24,
    }


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "cfg.json"
    cfg = config.default_config()
    config.save_config(path, cfg)
    assert config.load_config(path) == cfg


def test_load_missing_file_returns_default(tmp_path):
    path = tmp_path / "missing.json"
    assert config.load_config(path) == config.default_config()


def test_load_config_migrates_old_flat_bind_format(tmp_path):
    """Старые config.json — плоский словарь биндов без ключей "binds"/
    "panel". load_config должен обернуть его в новый формат при чтении, не
    трогая файл на диске."""
    path = tmp_path / "cfg.json"
    flat = {"1": {"name": "VS Code", "command": "code", "processes": ["Code"], "modifiers": ["alt"]}}
    path.write_text(json.dumps(flat), encoding="utf-8")

    cfg = config.load_config(path)

    assert cfg == {"binds": flat, "panel": config.default_panel_settings()}
    # Файл на диске не тронут — миграция происходит только при чтении.
    assert json.loads(path.read_text(encoding="utf-8")) == flat


def test_load_config_leaves_new_nested_format_unchanged(tmp_path):
    path = tmp_path / "cfg.json"
    nested = {"binds": {}, "panel": {"trigger": "hover", "side": "left", "hide_delay": None}}
    path.write_text(json.dumps(nested), encoding="utf-8")

    # Явно заданные значения не трогает; ключи, отсутствующие в файле
    # (например добавленные позже icon_spacing/edge_offset), дополняет
    # дефолтами — см. test_load_config_fills_missing_panel_keys_with_defaults.
    loaded = config.load_config(path)
    assert loaded["binds"] == nested["binds"]
    assert loaded["panel"]["trigger"] == "hover"
    assert loaded["panel"]["side"] == "left"
    assert loaded["panel"]["hide_delay"] is None


def test_load_config_fills_missing_panel_keys_with_defaults(tmp_path):
    path = tmp_path / "cfg.json"
    nested = {"binds": {}, "panel": {"trigger": "hover", "side": "left", "hide_delay": None}}
    path.write_text(json.dumps(nested), encoding="utf-8")

    loaded = config.load_config(path)

    assert loaded["panel"]["icon_spacing"] == config.default_panel_settings()["icon_spacing"]
    assert loaded["panel"]["edge_offset"] == config.default_panel_settings()["edge_offset"]
    # Файл на диске не тронут.
    assert json.loads(path.read_text(encoding="utf-8")) == nested


def test_add_bind_appends_new_entry_without_mutating_input():
    binds = {}
    new_binds = config.add_bind(binds, "3", "Telegram", "Telegram.exe", ["Telegram"], ["alt"])
    assert new_binds["3"]["name"] == "Telegram"
    assert binds == {}


def test_add_bind_rejects_out_of_range_number():
    with pytest.raises(ValueError):
        config.add_bind({}, "10", "X", "x.exe", ["X"], ["alt"])


def test_add_bind_rejects_zero_reserved_for_panel():
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
    binds = config.default_binds()
    new_binds = config.remove_bind(binds, "1")
    assert "1" not in new_binds
    assert "1" in binds


def test_remove_missing_bind_raises():
    with pytest.raises(KeyError):
        config.remove_bind({}, "5")


def test_next_free_bind_number_finds_first_gap():
    binds = {"1": {}, "2": {}, "4": {}}
    assert config.next_free_bind_number(binds) == "3"


def test_next_free_bind_number_on_empty_binds():
    assert config.next_free_bind_number({}) == "1"


def test_next_free_bind_number_returns_none_when_all_taken():
    binds = {str(n): {} for n in range(1, 10)}
    assert config.next_free_bind_number(binds) is None
