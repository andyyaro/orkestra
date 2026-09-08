"""Orkestra: a deterministic runtime for orchestrating coding-agent CLIs."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("orkestra-runtime")
except PackageNotFoundError:  # pragma: no cover - a source tree with no install
    # Only reachable when the package is imported without being installed,
    # which no shipped path does.
    __version__ = "0.0.0+unknown"
