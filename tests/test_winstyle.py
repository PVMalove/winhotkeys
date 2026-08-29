from winhotkeys import winstyle


def test_enable_window_blur_calls_winapi_and_reports_success(monkeypatch):
    captured = {}

    def fake_set_attr(hwnd, data_ptr):
        captured["hwnd"] = hwnd
        return 1

    monkeypatch.setattr(winstyle.user32, "SetWindowCompositionAttribute", fake_set_attr, raising=False)

    result = winstyle.enable_window_blur(12345)

    assert result is True
    assert captured["hwnd"] == 12345


def test_enable_window_blur_reports_failure_without_raising(monkeypatch):
    monkeypatch.setattr(winstyle.user32, "SetWindowCompositionAttribute", lambda hwnd, data: 0, raising=False)

    assert winstyle.enable_window_blur(12345) is False


def test_enable_window_blur_survives_os_error(monkeypatch):
    def raise_os_error(hwnd, data):
        raise OSError("boom")

    monkeypatch.setattr(winstyle.user32, "SetWindowCompositionAttribute", raise_os_error, raising=False)

    assert winstyle.enable_window_blur(12345) is False
