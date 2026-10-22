import os
import stat

from grab import config


def mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_config_and_data_dirs_are_private_even_when_they_already_exist(tmp_path, monkeypatch):
    cfg_dir, data_dir = tmp_path / "cfg", tmp_path / "data"
    cfg_dir.mkdir(mode=0o755)
    data_dir.mkdir(mode=0o755)
    monkeypatch.setenv("GRAB_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("GRAB_DATA_DIR", str(data_dir))
    config.load()
    assert mode(cfg_dir) == 0o700
    assert mode(data_dir) == 0o700
    assert mode(cfg_dir / "config.json") == 0o600
