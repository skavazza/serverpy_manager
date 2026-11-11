import json
import pytest
from pathlib import Path
from vendor.processhunter.core.config import ConfigManager, ConfigData, TargetItem

def test_default_config_creation(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    manager = ConfigManager(config_path=cfg_file)
    data = manager.load()

    assert cfg_file.exists()
    assert isinstance(data, ConfigData)
    assert data.sentinel_interval_seconds == 5
    assert data.autostart is False
    assert data.start_minimized is True
    assert data.minimize_to_tray_on_close is True
    assert data.notify_on_kill is True
    assert len(data.targets) == 1
    assert data.targets[0].name == "msedgewebview2d"
    assert data.targets[0].enabled is True

def test_save_and_reload_config(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    manager = ConfigManager(config_path=cfg_file)
    manager.load()

    added = manager.add_target("spotify.exe")
    assert added is True
    manager.set_sentinel_interval(10)

    # Reload from fresh manager
    manager2 = ConfigManager(config_path=cfg_file)
    data2 = manager2.load()

    assert data2.sentinel_interval_seconds == 10
    target_names = [t.name for t in data2.targets]
    assert "spotify" in target_names
    assert "msedgewebview2d" in target_names

def test_add_duplicate_target(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    manager = ConfigManager(config_path=cfg_file)
    manager.load()

    assert manager.add_target("Discord.EXE") is True
    assert manager.add_target("discord") is False  # duplicate normalized

def test_remove_target(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    manager = ConfigManager(config_path=cfg_file)
    manager.load()

    manager.add_target("notepad")
    assert manager.remove_target("notepad.exe") is True
    assert manager.remove_target("notepad") is False

def test_toggle_target(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    manager = ConfigManager(config_path=cfg_file)
    manager.load()

    assert manager.toggle_target("msedgewebview2d", False) is True
    item = next(t for t in manager.config.targets if t.name == "msedgewebview2d")
    assert item.enabled is False

def test_corrupted_json_recovery(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("{invalid json content!!!", encoding="utf-8")

    manager = ConfigManager(config_path=cfg_file)
    data = manager.load()

    assert isinstance(data, ConfigData)
    bak_file = tmp_path / "config.json.bak"
    assert bak_file.exists()
    assert "{invalid json" in bak_file.read_text(encoding="utf-8")
    assert cfg_file.exists()


def test_get_active_targets_snapshot(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    manager = ConfigManager(config_path=cfg_file)
    manager.load()

    manager.add_target("target1")
    manager.add_target("target2")
    manager.toggle_target("target2", False)

    active = manager.get_active_targets()
    assert "target1" in active
    assert "msedgewebview2d" in active
    assert "target2" not in active
