from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Tuple


@dataclass
class LogEvent:
    timestamp: str
    level: str
    message: str


class MemoryLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self._callbacks: List[Callable[[LogEvent], None]] = []

    def register_callback(self, callback: Callable[[LogEvent], None]) -> None:
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[LogEvent], None]) -> None:
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
            msg = self.format(record)
            event = LogEvent(
                timestamp=timestamp,
                level=record.levelname,
                message=msg
            )
            for cb in self._callbacks:
                try:
                    cb(event)
                except Exception:
                    pass
        except Exception:
            self.handleError(record)


def setup_app_logger(
    log_file: Path | str | None = None,
    logger_name: str = "ProcessHunter"
) -> Tuple[logging.Logger, MemoryLogHandler]:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    if log_file is None:
        appdata = os.environ.get("APPDATA")
        if appdata:
            log_dir = Path(appdata) / "ProcessHunter"
        else:
            log_dir = Path.home() / ".processhunter"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "processhunter.log"
    else:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s - [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        filename=str(log_file),
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    memory_handler = MemoryLogHandler()
    memory_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(memory_handler)

    return logger, memory_handler
