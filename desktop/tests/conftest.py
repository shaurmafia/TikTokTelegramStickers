import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIX = os.path.join(ROOT, "desktop", "tests", "fixtures")


@pytest.fixture(scope="session")
def fixtures_dir():
    assert os.path.isdir(FIX), "run tools/make_fixtures.py first"
    return FIX


@pytest.fixture()
def workspace(tmp_path):
    from desktop.core.file_manager import Workspace
    ws = Workspace(str(tmp_path / "ws"))
    ws.ensure_dirs()
    return ws
