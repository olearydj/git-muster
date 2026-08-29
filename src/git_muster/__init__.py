"""Git Muster public package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("git-muster")
except PackageNotFoundError:  # pragma: no cover - editable source without metadata
    __version__ = "0.0.0"

__all__ = ["__version__"]
