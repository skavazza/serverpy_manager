from unittest.mock import MagicMock
import pytest
from PySide6.QtCore import QCoreApplication
from vendor.processhunter.core.hunter import KillResult, ProcessInfo
from vendor.processhunter.ui.workers import SentinelWorker, ProcessScannerWorker


@pytest.fixture(scope="session")
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_process_scanner_worker(qapp):
    mock_hunter = MagicMock()
    mock_hunter.scan_active_processes.return_value = [
        ProcessInfo(pid=1, name="proc1", memory_mb=10.0, status="running")
    ]

    worker = ProcessScannerWorker(hunter=mock_hunter)
    received = []
    worker.scan_completed.connect(received.append)

    worker.run()  # direct call to run for deterministic unit testing
    assert len(received) == 1
    assert received[0][0].name == "proc1"


def test_sentinel_worker_run_once(qapp):
    mock_hunter = MagicMock()
    mock_hunter.kill_targets.return_value = [
        KillResult(pid=42, name="bad_process", success=True)
    ]

    mock_config = MagicMock()
    mock_config.config.targets = [
        MagicMock(name="bad_process", enabled=True)
    ]
    mock_config.config.sentinel_interval_seconds = 1

    worker = SentinelWorker(hunter=mock_hunter, config_manager=mock_config)
    results = []
    worker.hunt_completed.connect(results.append)

    worker.hunt_step()  # single step execution
    assert len(results) == 1
    assert results[0][0].pid == 42
    mock_hunter.kill_targets.assert_called_once()
