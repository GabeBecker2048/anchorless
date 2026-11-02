"""Themes: how the newscast looks."""

from __future__ import annotations

from ..config import Config

THEMES = ("studio", "classic", "classic-light", "classic-dark")


def make_theme(cfg: Config, name: str | None = None, channel_name: str | None = None):
    name = name or cfg.channel.theme
    if name == "classic":                       # light by day, dark at night
        from .pages import AutoClassicTheme

        return AutoClassicTheme(cfg, channel_name)
    if name in ("classic-light", "classic-dark"):
        from .pages import ClassicTheme

        return ClassicTheme(cfg, channel_name, dark=name == "classic-dark")
    from .studio import StudioTheme

    return StudioTheme(cfg, channel_name)
