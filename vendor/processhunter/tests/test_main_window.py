import pytest
from unittest.mock import MagicMock
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QCloseEvent
from vendor.processhunter.core.config import ConfigManager
from vendor.processhunter.core.hunter import ProcessHunter
from vendor.processhunter.core.autostart import WindowsAutostart
from vendor.processhunter.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_main_window_init_and_components(qapp, tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    config_manager = ConfigManager(config_path=cfg_file)
    config_manager.load()
    config_manager.add_target("testproc")

    hunter = MagicMock(spec=ProcessHunter)
    hunter.scan_active_processes.return_value = []
    hunter.kill_targets.return_value = []

    autostart = MagicMock(spec=WindowsAutostart)
    autostart.is_enabled.return_value = False

    window = MainWindow(
        config_manager=config_manager,
        hunter=hunter,
        autostart=autostart
    )

    # Verify components are present
    assert window.target_list_widget is not None
    assert window.process_table_widget is not None
    assert window.log_view is not None
    assert window.btn_hunt_now is not None
    assert window.btn_toggle_sentinel is not None

    # Verify targets loaded into target_list_widget
    assert len(window.target_list_widget._targets) == 2  # default msedgewebview2d + testproc

    # Test closeEvent intercepts and ignores event to minimize to tray
    close_event = QCloseEvent()
    window.closeEvent(close_event)
    assert close_event.isAccepted() is False
    assert window.isVisible() is False


def test_force_exit_quits_qapplication(qapp, tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    config_manager = ConfigManager(config_path=cfg_file)
    config_manager.load()

    hunter = MagicMock(spec=ProcessHunter)
    autostart = MagicMock(spec=WindowsAutostart)

    window = MainWindow(config_manager=config_manager, hunter=hunter, autostart=autostart)

    quit_mock = MagicMock()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(qapp, "quit", quit_mock)
        window.force_exit()
        quit_mock.assert_called_once()


def test_close_event_quits_when_minimize_disabled(qapp, tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    config_manager = ConfigManager(config_path=cfg_file)
    config_manager.load()
    config_manager.config.minimize_to_tray_on_close = False

    hunter = MagicMock(spec=ProcessHunter)
    autostart = MagicMock(spec=WindowsAutostart)

    window = MainWindow(config_manager=config_manager, hunter=hunter, autostart=autostart)

    quit_mock = MagicMock()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(qapp, "quit", quit_mock)
        close_event = QCloseEvent()
        window.closeEvent(close_event)
        assert close_event.isAccepted() is True
        quit_mock.assert_called_once()


def test_main_window_logs_to_logger(qapp, tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    config_manager = ConfigManager(config_path=cfg_file)
    config_manager.load()

    mock_logger = MagicMock()
    hunter = MagicMock(spec=ProcessHunter)
    autostart = MagicMock(spec=WindowsAutostart)

    window = MainWindow(
        config_manager=config_manager,
        hunter=hunter,
        autostart=autostart,
        logger=mock_logger
    )

    window.append_log_message("SUCCESS", "Processo encerrado com sucesso")
    mock_logger.info.assert_called_with("Processo encerrado com sucesso")
