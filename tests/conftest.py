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
