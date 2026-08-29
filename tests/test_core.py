import pytest

from winhotkeys.core import (
    EdgeDwellTracker,
    find_index,
    is_cursor_at_edge,
    pick_next_action,
)


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


def test_is_cursor_at_edge_right_side_true_near_edge():
    assert is_cursor_at_edge(1914, 0, 1920, "right", threshold_px=6) is True


def test_is_cursor_at_edge_right_side_false_away_from_edge():
    assert is_cursor_at_edge(1000, 0, 1920, "right", threshold_px=6) is False


def test_is_cursor_at_edge_left_side_true_near_edge():
    assert is_cursor_at_edge(3, 0, 1920, "left", threshold_px=6) is True


def test_is_cursor_at_edge_left_side_false_away_from_edge():
    assert is_cursor_at_edge(500, 0, 1920, "left", threshold_px=6) is False


def test_is_cursor_at_edge_rejects_unknown_side():
    with pytest.raises(ValueError):
        is_cursor_at_edge(0, 0, 1920, "top")


def test_edge_dwell_tracker_requires_continuous_presence():
    tracker = EdgeDwellTracker(dwell_seconds=0.25)
    assert tracker.update(True, now=0.0) is False
    assert tracker.update(True, now=0.1) is False
    assert tracker.update(True, now=0.25) is True


def test_edge_dwell_tracker_resets_when_cursor_leaves_zone():
    tracker = EdgeDwellTracker(dwell_seconds=0.25)
    assert tracker.update(True, now=0.0) is False
    assert tracker.update(False, now=0.1) is False
    # Курсор вернулся в зону — отсчёт должен начаться заново, а не
    # продолжиться с прежней точки.
    assert tracker.update(True, now=0.2) is False
    assert tracker.update(True, now=0.44) is False
    assert tracker.update(True, now=0.45) is True


def test_edge_dwell_tracker_never_in_zone_stays_false():
    tracker = EdgeDwellTracker(dwell_seconds=0.25)
    assert tracker.update(False, now=0.0) is False
    assert tracker.update(False, now=10.0) is False
