import pytest

pytest.importorskip("PySide6")

from winhotkeys.panel import PALETTE, _placeholder_color


def test_placeholder_color_is_deterministic_and_in_palette():
    assert _placeholder_color("VS Code") in PALETTE
    assert _placeholder_color("VS Code") == _placeholder_color("VS Code")


def test_placeholder_color_varies_by_name():
    # Не гарантия отсутствия коллизий (палитра всего из 8 цветов), но
    # ловит совсем сломанную реализацию, игнорирующую имя.
    colors = {_placeholder_color(name) for name in ("VS Code", "Docker", "Telegram", "Chrome")}
    assert len(colors) > 1
