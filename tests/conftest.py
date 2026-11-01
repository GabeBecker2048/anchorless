from datetime import UTC, datetime
from pathlib import Path

import pytest

from anchorless.config import Config, SourceConfig
from anchorless.sources.rss import parse_feed

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 1, 17, 0, tzinfo=UTC)


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(
        source=[SourceConfig(name="Outlet A", url="https://a.example/rss"),
                SourceConfig(name="Outlet B", url="https://b.example/rss")],
        data={"dir": str(tmp_path)},
    )


@pytest.fixture
def stories(cfg):
    out = []
    for name, src in (("outlet_a.xml", cfg.source[0]), ("outlet_b.xml", cfg.source[1])):
        out += parse_feed((FIXTURES / name).read_bytes(), src)
    return out
