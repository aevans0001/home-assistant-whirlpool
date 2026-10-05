"""Pytest harness for the integration-layer unit tests.

Design (PASS 8 harness fix, extended for the regular-washer recovery baseline):

* The real sixth-sense library owns the top-level ``whirlpool`` package.
  By default that is ``library/whirlpool-sixth-sense`` (the working tree).
  Set the environment variable ``WHISK_LIBRARY_DIR`` to test against a
  different library checkout, e.g. the baseline pin 60e0867 exported with
  ``git archive``. That override is how the baseline tests are proven against
  the exact library the baseline manifest installs.
* * ``custom_components/whirlpool/`` is NEVER placed on ``sys.path``. That directory
  contains ``select.py``, which would shadow the stdlib ``select`` module, and
  its ``__init__.py`` is the Home Assistant integration package, not the
  library.
* ``tests/pytest.ini`` pins the rootdir here, and ``tests/`` has no
  ``__init__.py``, so pytest never imports the integration package as
  ``whirlpool``.

Recovery baseline: the Configure/Send staging test modules are PARKED (not
collected) because the baseline removes staging from the production wiring.
The files are kept unchanged for the later staging rebuild.

These tests do NOT require Home Assistant.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent
_INTEGRATION_PKG_DIR = _REPO_ROOT / "custom_components" / "whirlpool"
_LEGACY_ROOT = _REPO_ROOT.parent.parent  # legacy/
_LIBRARY_DIR = Path(
    os.environ.get("WHISK_LIBRARY_DIR")
    or (_LEGACY_ROOT / "library" / "whirlpool-sixth-sense")
).resolve()

STAGING_MODULE_NAME = "whisk_integration_washer_staging"

# Staging-era modules: parked for the regular-washer recovery baseline.
collect_ignore = [
    "test_washer_staging.py",
    "test_washer_send.py",
    "test_washer_remote_modes.py",
]


def _same_path(a: str, b: Path) -> bool:
    try:
        return Path(a or ".").resolve() == b
    except OSError:
        return False


# 1. The integration package directory must never be on sys.path.
sys.path[:] = [p for p in sys.path if not _same_path(p, _INTEGRATION_PKG_DIR)]

# 2. The chosen library owns the top-level ``whirlpool`` package.
_library = str(_LIBRARY_DIR)
if _library in sys.path:
    sys.path.remove(_library)
sys.path.insert(0, _library)

import whirlpool  # noqa: E402  (must follow the sys.path setup above)

_whirlpool_file = Path(whirlpool.__file__ or "<no __file__>").resolve()
if _whirlpool_file.parent == _INTEGRATION_PKG_DIR:
    raise RuntimeError(
        "Test harness error: top-level 'whirlpool' resolved to the HA "
        f"integration package ({_whirlpool_file}) instead of the "
        "sixth-sense library."
    )
if _whirlpool_file.parent.parent != _LIBRARY_DIR:
    raise RuntimeError(
        f"Test harness error: 'whirlpool' resolved to {_whirlpool_file}, "
        f"not the requested library {_LIBRARY_DIR}."
    )

# 3. The stdlib ``select`` must be the real one, not custom_components/whirlpool/select.py.
import select as _stdlib_select  # noqa: E402

_select_file = getattr(_stdlib_select, "__file__", None)  # None when built in
if _select_file and Path(_select_file).resolve().parent == _INTEGRATION_PKG_DIR:
    raise RuntimeError(
        f"Test harness error: stdlib 'select' is shadowed by {_select_file}."
    )

# 4. Staging module (only if still present): loaded under a test-only name for
#    the parked staging tests. The baseline production wiring does not use it.
_staging_file = _INTEGRATION_PKG_DIR / "washer_staging.py"
if _staging_file.exists():
    _spec = importlib.util.spec_from_file_location(STAGING_MODULE_NAME, _staging_file)
    if _spec is not None and _spec.loader is not None:
        _module = importlib.util.module_from_spec(_spec)
        sys.modules[STAGING_MODULE_NAME] = _module
        _spec.loader.exec_module(_module)
