import pytest

pytest.importorskip("customtkinter")

from winhotkeys import config as config_mod, settings_window


def test_trigger_options_match_config_valid_triggers():
    """Регрессия: если в config.py появится/исчезнет допустимый триггер,
    список радиокнопок окна настроек должен обновиться вместе с ним —
    иначе в UI можно выбрать значение, которого нет в схеме (или наоборот,
    новый режим останется недоступен в интерфейсе)."""
    values = {value for value, _title, _desc in settings_window.TRIGGER_OPTIONS}
    assert values == config_mod.VALID_TRIGGERS


def test_hide_delay_labels_match_config_valid_hide_delays():
    assert set(settings_window.HIDE_DELAY_LABELS) == config_mod.VALID_HIDE_DELAYS


def test_hide_delay_label_lookup_round_trips():
    for value, label in settings_window.HIDE_DELAY_LABELS.items():
        assert settings_window.HIDE_DELAY_BY_LABEL[label] == value
