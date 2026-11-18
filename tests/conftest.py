import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_prebuilt_console_data(tmp_path_factory, monkeypatch):
    """Tests build the console data themselves: files in prebuilt/ (from scripts/build_console_data.py) are not read."""
    from webapp import data
    monkeypatch.setattr(data, "PREBUILT", tmp_path_factory.mktemp("prebuilt"))


@pytest.fixture(autouse=True)
def _no_writes_to_the_real_screening_meta(tmp_path_factory, monkeypatch):
    """gfw_fetch.fetch_screening writes library/screening_list.json; tests must never touch the real one."""
    import gfw_fetch
    monkeypatch.setattr(gfw_fetch, "SCREENING_META", tmp_path_factory.mktemp("screening") / "screening_list.json")
