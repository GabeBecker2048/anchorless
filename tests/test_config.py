import pytest

from anchorless.config import ConfigError, load_config


def test_defaults_without_a_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config(environ={})
    assert cfg.video.width == 854 and cfg.stream.port == 9798
    assert [s.name for s in cfg.rundown.segment][0] == "TOP STORIES"
    assert len(cfg.source) > 10


def test_example_config_is_valid():
    from pathlib import Path
    cfg = load_config(Path(__file__).parent.parent / "config.example.toml", environ={})
    assert cfg.channel.name


def test_env_overrides(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[channel]\nname = "WIRE"\n')
    cfg = load_config(p, environ={"ANCHORLESS__LOCATION__CITY": "Springfield", "ANCHORLESS__VIDEO__FPS": "30"})
    assert cfg.channel.name == "WIRE"
    assert cfg.location.city == "Springfield"
    assert cfg.video.fps == 30


def test_typos_are_errors(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[video]\nwidht = 854\n")
    with pytest.raises(ConfigError, match="widht"):
        load_config(p, environ={})


def test_odd_size_rejected(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[video]\nwidth = 855\n")
    with pytest.raises(ConfigError, match="even"):
        load_config(p, environ={})


def test_bad_exclude_pattern(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[[source]]\nname = "X"\nurl = "https://x"\nexclude = ["("]\n')
    with pytest.raises(ConfigError, match="bad pattern"):
        load_config(p, environ={})
