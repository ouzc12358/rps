"""BSL/FS calibration toolkit."""

from importlib.metadata import PackageNotFoundError, version

try:  # pragma: no cover - fallback when package metadata missing
    __version__ = version("bslfs")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = ["__version__"]
