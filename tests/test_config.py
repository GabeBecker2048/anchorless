import pytest

from anchorless.config import ConfigError, load_config

MINIMAL = '[channel]\ntheme = "studio"\nshow_on = "both"\nchannel_number = 101\n'


def test_minimal_file_gets_defaults(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(MINIMAL)
    cfg = load_config(p, environ={})
    assert cfg.video.width == 854 and cfg.stream.port == 9798
    assert cfg.channel.name == "NEWS" and cfg.channel.channel_number == "101"
    assert [s.name for s in cfg.rundown.segment][0] == "TOP STORIES"
    assert len(cfg.source) > 10


def test_channel_settings_are_required(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="channel"):
        load_config(environ={})                              # no file: no [channel]
    p = tmp_path / "c.toml"
    p.write_text('[channel]\ntheme = "studio"\nshow_on = "tv"\n')
    with pytest.raises(ConfigError, match="channel_number is required"):
        load_config(p, environ={})
    p.write_text('[channel]\ntheme = "studio"\nshow_on = "web"\nchannel_number = 7\n')
    assert load_config(p, environ={}).channel.channel_number is None     # ignored for web


def test_channel_numbers(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(MINIMAL.replace("101", '"2.1"'))
    assert load_config(p, environ={}).channel.channel_number == "2.1"
    p.write_text(MINIMAL.replace("101", '"two"'))
    with pytest.raises(ConfigError, match="must be a number"):
        load_config(p, environ={})
    p.write_text(MINIMAL + '[[extra_channel]]\ntheme = "classic"\nname = "B"\nshow_on = "tv"\nchannel_number = 101\n')
    with pytest.raises(ConfigError, match="same channel_number"):
        load_config(p, environ={})


def test_extra_channel_needs_a_name(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(MINIMAL + '[[extra_channel]]\ntheme = "classic"\nshow_on = "web"\n')
    with pytest.raises(ConfigError, match="name"):
        load_config(p, environ={})


def test_moved_settings_say_where_they_went(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[channel]\nnumber = "98"\n[theme]\nname = "studio"\n')
    with pytest.raises(ConfigError, match="now \\[channel\\] theme.*now channel_number"):
        load_config(p, environ={})


def test_example_config_is_valid():
    from pathlib import Path
    cfg = load_config(Path(__file__).parent.parent / "config.example.toml", environ={})
    assert cfg.channel.name


def test_env_overrides(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(MINIMAL + 'name = "WIRE"\n')
    cfg = load_config(p, environ={"ANCHORLESS__LOCATION__CITY": "Springfield", "ANCHORLESS__VIDEO__FPS": "30"})
    assert cfg.channel.name == "WIRE"
    assert cfg.location.city == "Springfield"
    assert cfg.video.fps == 30


def test_typos_are_errors(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(MINIMAL + "[video]\nwidht = 854\n")
    with pytest.raises(ConfigError, match="widht"):
        load_config(p, environ={})


def test_odd_size_rejected(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(MINIMAL + "[video]\nwidth = 855\n")
    with pytest.raises(ConfigError, match="even"):
        load_config(p, environ={})


def test_bad_exclude_pattern(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(MINIMAL + '[[source]]\nname = "X"\nurl = "https://x"\nexclude = ["("]\n')
    with pytest.raises(ConfigError, match="bad pattern"):
        load_config(p, environ={})
