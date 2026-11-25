import os
import sys

from compas.tolerance import TOL
import pytest

# pytest runs with --import-mode=importlib, which does not put the test folder on sys.path,
# so add it here for the tests that import the sibling `brep_mocks` helper module.
sys.path.insert(0, os.path.dirname(__file__))


def pytest_collection_modifyitems(items):
    if sys.version_info >= (3, 10):
        return
    skip_occ = pytest.mark.skip(reason="OCC Brep backend is not available on Python 3.9")
    for item in items:
        if "requires_occ" in item.keywords:
            item.add_marker(skip_occ)


@pytest.fixture(autouse=True, scope="session")
def tolerance_session_default():
    # Session scope is broader than module scope, so this runs before any
    # module-scoped fixture build - including the first one in the whole run,
    # which the function-scoped reset_tolerance below cannot cover.
    TOL.reset()
    TOL.unit = "MM"


@pytest.fixture(autouse=True)
def reset_tolerance():
    """
    Reset the global tolerance before and after each test.
    This fixture is automatically applied to all tests.
    It enforces test isolation by ensuring that no test depends on tolerance values modified by other tests.
    Tests that require a non-default tolerance must set it explicitly within their own scope.
    """
    TOL.reset()
    TOL.unit = "MM"
    yield
    TOL.reset()
    TOL.unit = "MM"
