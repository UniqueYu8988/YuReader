"""Bridge so `python -m unittest discover -s tests` also finds YuPractice tests.

The authoritative tests live in tools/yupractice/tests/test_yupractice.py and are
also runnable directly with `python -m unittest discover -s tools/yupractice/tests`.
This file only re-exports them under the top-level tests directory; it does not
duplicate test logic.
"""

import sys
from pathlib import Path

_TOOLS_YUPRACTICE_TESTS = (
    Path(__file__).resolve().parent.parent / "tools" / "yupractice" / "tests"
)
sys.path.insert(0, str(_TOOLS_YUPRACTICE_TESTS))

from test_yupractice import *  # noqa: F401,F403,E402  (re-export for discovery)