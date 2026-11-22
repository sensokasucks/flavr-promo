import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_custom_groups():
    """Each test starts with only the built-in groups (FlaVR, Friends, Community) (flavrpromo/groups.py keeps its store in a module global)."""
    from flavrpromo import groups
    groups.init(None)
    yield
    groups.init(None)


@pytest.fixture(autouse=True)
def _banter_on():
    """Each test starts with the hosts answering each other and every built-in extra picture in use (the
    defaults; flavrpromo/hosts.py keeps both in module globals that hosts.load_overrides sets)."""
    from flavrpromo import hosts, kobold
    hosts._banter, hosts._hidden = True, frozenset()
    kobold._angle_edits.clear()
    yield
    hosts._banter, hosts._hidden = True, frozenset()
    kobold._angle_edits.clear()
