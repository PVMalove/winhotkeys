import pytest

from winhotkeys.core import find_index, pick_next_action


def test_no_active_window_focuses_first():
    assert pick_next_action(3, None) == ("focus", 0)


def test_advances_to_next_window():
    assert pick_next_action(3, 0) == ("focus", 1)
    assert pick_next_action(3, 1) == ("focus", 2)


def test_minimizes_on_last_window_instead_of_wrapping():
    assert pick_next_action(3, 2) == ("minimize", 2)


def test_single_window_toggles_between_focus_and_minimize():
    # окно ещё не активно (например, свёрнуто или фокус в другой программе) -> фокусируем
    assert pick_next_action(1, None) == ("focus", 0)
    # окно уже активно (единственное) -> повторное нажатие сворачивает
    assert pick_next_action(1, 0) == ("minimize", 0)


def test_stale_index_resets_to_focus_first():
    assert pick_next_action(3, 99) == ("focus", 0)


def test_rejects_empty_window_list():
    with pytest.raises(ValueError):
        pick_next_action(0, None)


def test_find_index_found():
    assert find_index([10, 20, 30], 20) == 1


def test_find_index_not_found():
    assert find_index([10, 20, 30], 99) is None


def test_find_index_no_active_window():
    assert find_index([10, 20, 30], None) is None
