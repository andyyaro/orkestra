"""Suite-wide fixtures and guards.

Currently one thing only: the switch that stops the optional-memory suite from
certifying itself by skipping.
"""

from __future__ import annotations

import os

#: Environment variable that makes a missing Provalume extra a failure rather
#: than a skip.
REQUIRE_MEMORY_EXTRA_ENV = "ORKESTRA_REQUIRE_MEMORY_EXTRA"

_FALSEY = {"", "0", "false", "no", "off"}


def missing_memory_extra_is_fatal() -> bool:
    """Whether an absent Provalume must fail the run instead of skipping it.

    ``tests/test_memory.py`` is the only module that drives the Provalume bridge
    against a real database, and it is guarded by an import skip because the
    extra is genuinely optional. That skip is silent: a gate that installs no
    extras reports green while the feature the branch exists to add goes
    entirely unrun — which is indistinguishable, from the outside, from a gate
    that verified it.

    Any run that means to certify memory sets ``ORKESTRA_REQUIRE_MEMORY_EXTRA``
    (with the ``memory`` extra installed) and gets a hard failure instead.
    """
    return os.environ.get(REQUIRE_MEMORY_EXTRA_ENV, "").strip().lower() not in _FALSEY
