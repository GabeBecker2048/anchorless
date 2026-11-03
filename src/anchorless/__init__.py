"""Anchorless: a 24/7 text newscast for IPTV."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("anchorless")     # one source of truth: pyproject.toml
except PackageNotFoundError:                 # running from a source tree that isn't installed
    __version__ = "0+unknown"
