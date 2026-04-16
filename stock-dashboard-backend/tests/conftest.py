import os
import tempfile
import pytest

# Must be set before main.py is imported by any test module.
# conftest.py is loaded by pytest before test files are collected.
_test_db = tempfile.mktemp(suffix="_test.db")
os.environ["MARKETLENS_DB"] = _test_db


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    yield
    try:
        if os.path.exists(_test_db):
            os.unlink(_test_db)
    except OSError:
        pass  # Windows may hold the file open; ignore on teardown
