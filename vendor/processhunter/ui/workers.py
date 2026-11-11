from __future__ import annotations
import time
from typing import List
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker
from vendor.processhunter.core.hunter import ProcessHunter, ProcessInfo, KillResult
from vendor.processhunter.core.config import ConfigManager


class ProcessScannerWorker(QThread):
    scan_completed = Signal(list)  # List[ProcessInfo]
    scan_failed = Signal(str)

    def __init__(self, hunter: ProcessHunter, parent=None) -> None:
        super().__init__(parent)
        self.hunter = hunter

    def run(self) -> None:
        try:
            processes = self.hunter.scan_active_processes()
            self.scan_completed.emit(processes)
        except Exception as ex:
            self.scan_failed.emit(str(ex))


class SentinelWorker(QThread):
    hunt_completed = Signal(list)  # List[KillResult]
    status_changed = Signal(bool)
    log_message = Signal(str, str)  # (level, message)

    def __init__(
        self,
        hunter: ProcessHunter,
        config_manager: ConfigManager,
        parent=None
    ) -> None:
        super().__init__(parent)
        self.hunter = hunter
        self.config_manager = config_manager
        self._is_running = False
        self._mutex = QMutex()
        self._interval_seconds = 5

    def set_interval(self, seconds: int) -> None:
        with QMutexLocker(self._mutex):
            self._interval_seconds = max(1, seconds)

    def stop(self) -> None:
        with QMutexLocker(self._mutex):
            self._is_running = False
        self.status_changed.emit(False)

    def is_sentinel_running(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._is_running

    def hunt_step(self) -> List[KillResult]:
        active_targets = self.config_manager.get_active_targets()
        if not active_targets:
            return []

        results = self.hunter.kill_targets(active_targets)
        if results:
            self.hunt_completed.emit(results)
        return results

    def run(self) -> None:
        with QMutexLocker(self._mutex):
            self._is_running = True
        self.status_changed.emit(True)
        self.log_message.emit("INFO", "Sentinela de monitoramento iniciada.")

        while True:
            with QMutexLocker(self._mutex):
                if not self._is_running:
                    break
                interval = self._interval_seconds

            try:
                self.hunt_step()
            except Exception as ex:
                self.log_message.emit("ERROR", f"Erro no ciclo da Sentinela: {ex}")

            # Sleep in 100ms slices to allow quick thread exit
            elapsed = 0.0
            while elapsed < interval:
                with QMutexLocker(self._mutex):
                    if not self._is_running:
                        break
                time.sleep(0.1)
                elapsed += 0.1

        self.log_message.emit("INFO", "Sentinela de monitoramento pausada.")
        self.status_changed.emit(False)
