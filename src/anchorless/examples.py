"""The example config files, shipped inside the package for `anchorless init`."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

NAMES = ("config.example.toml", "local.example.toml")


def example_text(name: str) -> str:
    """An example file's text: from the installed package, or the source tree."""
    if name not in NAMES:
        raise ValueError(name)
    packaged = files("anchorless") / name           # wheels carry it (pyproject force-include)
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    return (Path(__file__).resolve().parents[2] / name).read_text(encoding="utf-8")   # a checkout


def init(folder: Path, force: bool = False, filename: str = "config.toml") -> list[Path]:
    """Write a starter config (and local.example.toml) into ``folder``. Returns the files written."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / filename
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists (use --force to replace it)")
    target.write_text(example_text("config.example.toml"), encoding="utf-8")
    written = [target]
    local = folder / "local.example.toml"
    if not local.exists():
        local.write_text(example_text("local.example.toml"), encoding="utf-8")
        written.append(local)
    return written
