import pytest
from PySide6.QtWidgets import QApplication
from vendor.systemram.gui.main_window import MainWindow

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

def test_main_window_creation(qapp):
    win = MainWindow()
    assert win.windowTitle().startswith("PyRAMMap")
    assert win.tab_widget.count() == 3
    assert win.tab_widget.tabText(0) == "Use Counts"
    assert win.tab_widget.tabText(1) == "Processes"
    assert win.tab_widget.tabText(2) == "Priority Summary"

def test_main_window_menu_actions(qapp):
    win = MainWindow()
    # Menus
    menu_bar = win.menuBar()
    menus = [action.text() for action in menu_bar.actions()]
    assert "File" in menus or "&File" in menus
    assert "Empty" in menus or "&Empty" in menus
    assert "Help" in menus or "&Help" in menus

def test_rapid_refresh_guarded(qapp):
    win = MainWindow()
    # Calling refresh_data multiple times rapidly shouldn't crash
    win.refresh_data()
    win.refresh_data()
    win.refresh_data()
    assert win.worker is not None
