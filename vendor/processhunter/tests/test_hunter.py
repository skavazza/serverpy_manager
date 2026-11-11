from unittest.mock import MagicMock, patch
import pytest
import psutil
from vendor.processhunter.core.hunter import ProcessHunter, ProcessInfo, KillResult


def test_normalize_name():
    assert ProcessHunter.normalize_name("  Spotify.EXE  ") == "spotify"
    assert ProcessHunter.normalize_name("msedgewebview2d") == "msedgewebview2d"
    assert ProcessHunter.normalize_name("TEAMS.exe") == "teams"
    assert ProcessHunter.normalize_name("my_app.EXE") == "my_app"


def test_scan_active_processes():
    proc1 = MagicMock()
    proc1.info = {
        "pid": 100,
        "name": "explorer.exe",
        "memory_info": MagicMock(rss=104857600),  # 100 MB
        "status": "running",
    }

    proc2 = MagicMock()
    proc2.info = {
        "pid": 200,
        "name": "chrome.exe",
        "memory_info": MagicMock(rss=209715200),  # 200 MB
        "status": "running",
    }

    with patch("psutil.process_iter", return_value=[proc1, proc2]):
        hunter = ProcessHunter()
        procs = hunter.scan_active_processes()

        assert len(procs) == 2
        # Alphabetical sorting
        assert procs[0].name == "chrome.exe"
        assert procs[0].pid == 200
        assert procs[0].memory_mb == 200.0
        assert procs[1].name == "explorer.exe"


def test_kill_targets_success():
    proc = MagicMock()
    proc.info = {"pid": 555, "name": "Spotify.exe"}
    proc.kill = MagicMock()

    with patch("psutil.process_iter", return_value=[proc]):
        hunter = ProcessHunter()
        results = hunter.kill_targets(["spotify"])

        assert len(results) == 1
        assert results[0].pid == 555
        assert results[0].name == "Spotify.exe"
        assert results[0].success is True
        proc.kill.assert_called_once()


def test_kill_targets_access_denied():
    proc = MagicMock()
    proc.info = {"pid": 999, "name": "system_service.exe"}
    proc.kill = MagicMock(side_effect=psutil.AccessDenied(pid=999))

    with patch("psutil.process_iter", return_value=[proc]):
        hunter = ProcessHunter()
        results = hunter.kill_targets(["system_service.exe"])

        assert len(results) == 1
        assert results[0].pid == 999
        assert results[0].success is False
        assert "Permissão insuficiente" in results[0].error_message


def test_kill_targets_no_such_process():
    proc = MagicMock()
    proc.info = {"pid": 777, "name": "short_lived.exe"}
    proc.kill = MagicMock(side_effect=psutil.NoSuchProcess(pid=777))

    with patch("psutil.process_iter", return_value=[proc]):
        hunter = ProcessHunter()
        results = hunter.kill_targets(["short_lived"])

        assert len(results) == 1
        assert results[0].pid == 777
        assert results[0].success is True
        assert "já encerrado" in results[0].error_message
