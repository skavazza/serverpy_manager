import pytest
from PySide6.QtWidgets import QApplication
from vendor.processhunter.core.hunter import KillResult
from vendor.processhunter.ui.tray import HunterTrayIcon


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_tray_icon_signals_and_menu(qapp):
    tray = HunterTrayIcon()

    assert tray.contextMenu() is not None

    # Test update status text
    tray.update_status(is_sentinel_active=True)
    assert "Pausar" in tray.action_toggle_sentinel.text()
    assert "ATIVA" in tray.toolTip()

    tray.update_status(is_sentinel_active=False)
    assert "Iniciar" in tray.action_toggle_sentinel.text()
    assert "PAUSADA" in tray.toolTip()

    # Test signals triggered by menu actions
    restore_called = []
    hunt_called = []
    exit_called = []

    tray.restore_requested.connect(lambda: restore_called.append(True))
    tray.hunt_now_requested.connect(lambda: hunt_called.append(True))
    tray.exit_requested.connect(lambda: exit_called.append(True))

    tray.action_restore.trigger()
    tray.action_hunt_now.trigger()
    tray.action_exit.trigger()

    assert len(restore_called) == 1
    assert len(hunt_called) == 1
    assert len(exit_called) == 1
