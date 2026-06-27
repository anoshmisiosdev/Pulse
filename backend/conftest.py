"""Root conftest — its presence puts the backend dir on sys.path for `import app`."""

from datetime import datetime

import pytest

# A fixed "now" so time-based scoring assertions are deterministic.
NOW = datetime(2026, 6, 26)


@pytest.fixture
def now() -> datetime:
    return NOW
