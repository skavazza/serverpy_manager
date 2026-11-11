from __future__ import annotations
import json
import os
import re
import shutil
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


def normalize_target_name(name: str) -> str:
    cleaned = name.strip()
    cleaned = re.sub(r'(?i)\.exe$', '', cleaned)
    return cleaned.lower()


@dataclass
class TargetItem:
    name: str
    enabled: bool = True

    def __post_init__(self):
        self.name = normalize_target_name(self.name)


@dataclass
class ConfigData:
    targets: list[TargetItem] = field(default_factory=lambda: [TargetItem(name="msedgewebview2d", enabled=True)])
    sentinel_interval_seconds: int = 5
    autostart: bool = False
    start_minimized: bool = True
    minimize_to_tray_on_close: bool = True
    notify_on_kill: bool = True


class ConfigManager:
    def __init__(self, config_path: Path | str | None = None) -> None:
        self._lock = threading.RLock()
        if config_path is not None:
            self.config_path = Path(config_path)
        else:
            appdata = os.environ.get("APPDATA")
            if appdata:
                base_dir = Path(appdata) / "ProcessHunter"
            else:
                base_dir = Path.home() / ".processhunter"
            base_dir.mkdir(parents=True, exist_ok=True)
            self.config_path = base_dir / "config.json"

        self.config: ConfigData = ConfigData()

    def get_active_targets(self) -> List[str]:
        with self._lock:
            return [t.name for t in self.config.targets if t.enabled]

    def load(self) -> ConfigData:
        with self._lock:
            if not self.config_path.exists():
                self.config = ConfigData()
                self.save()
                return self.config

            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                targets = [
                    TargetItem(name=item.get("name", ""), enabled=item.get("enabled", True))
                    for item in data.get("targets", [])
                    if item.get("name")
                ]
                self.config = ConfigData(
                    targets=targets,
                    sentinel_interval_seconds=int(data.get("sentinel_interval_seconds", 5)),
                    autostart=bool(data.get("autostart", False)),
                    start_minimized=bool(data.get("start_minimized", True)),
                    minimize_to_tray_on_close=bool(data.get("minimize_to_tray_on_close", True)),
                    notify_on_kill=bool(data.get("notify_on_kill", True)),
                )
                return self.config
            except Exception:
                # Corrupted file: backup and return default
                bak_path = self.config_path.with_suffix(".json.bak")
                try:
                    shutil.copy2(self.config_path, bak_path)
                except Exception:
                    pass
                self.config = ConfigData()
                self.save()
                return self.config

    def save(self) -> None:
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            raw_data = {
                "targets": [asdict(t) for t in self.config.targets],
                "sentinel_interval_seconds": self.config.sentinel_interval_seconds,
                "autostart": self.config.autostart,
                "start_minimized": self.config.start_minimized,
                "minimize_to_tray_on_close": self.config.minimize_to_tray_on_close,
                "notify_on_kill": self.config.notify_on_kill,
            }
            # Atomic write
            temp_path = self.config_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.config_path)

    def add_target(self, name: str) -> bool:
        norm = normalize_target_name(name)
        if not norm:
            return False
        with self._lock:
            for item in self.config.targets:
                if item.name == norm:
                    return False
            self.config.targets.append(TargetItem(name=norm, enabled=True))
            self.save()
            return True

    def remove_target(self, name: str) -> bool:
        norm = normalize_target_name(name)
        with self._lock:
            initial_len = len(self.config.targets)
            self.config.targets = [t for t in self.config.targets if t.name != norm]
            if len(self.config.targets) < initial_len:
                self.save()
                return True
            return False

    def toggle_target(self, name: str, enabled: bool) -> bool:
        norm = normalize_target_name(name)
        with self._lock:
            for item in self.config.targets:
                if item.name == norm:
                    item.enabled = enabled
                    self.save()
                    return True
            return False

    def set_sentinel_interval(self, seconds: int) -> None:
        with self._lock:
            self.config.sentinel_interval_seconds = max(1, seconds)
            self.save()
