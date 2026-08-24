import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest


@pytest.fixture(autouse=True)
def _clear_win32api_discovery_cache():
    """win32api кэширует поиск процессов/окон на 0.2с по ключу с id()
    текущей (часто подменённой monkeypatch'ем) функции — CPython может
    переиспользовать id только что собранной GC лямбды между тестами,
    из-за чего один тест получает закэшированный результат другого."""
    from winhotkeys import win32api

    win32api.clear_discovery_cache()
    yield
    win32api.clear_discovery_cache()
