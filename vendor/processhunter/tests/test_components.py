import pytest
from PySide6.QtWidgets import QApplication
from vendor.processhunter.core.config import TargetItem
from vendor.processhunter.core.hunter import ProcessInfo
from vendor.processhunter.ui.components.process_table import ProcessTableWidget
from vendor.processhunter.ui.components.target_list import TargetListWidget


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_process_table_widget(qapp):
    widget = ProcessTableWidget()
    test_processes = [
        ProcessInfo(pid=100, name="notepad.exe", memory_mb=15.5, status="running"),
        ProcessInfo(pid=200, name="calc.exe", memory_mb=25.0, status="running")
    ]
    widget.set_processes(test_processes)

    # Filter test
    widget.search_input.setText("notep")
    assert widget.table.isRowHidden(0) is False  # notepad visible
    assert widget.table.isRowHidden(1) is True   # calc hidden

    # Signal test
    added_targets = []
    widget.add_target_requested.connect(added_targets.append)
    widget.table.selectRow(0)
    widget.btn_add_to_targets.click()
    assert added_targets == ["notepad.exe"]


def test_target_list_widget(qapp):
    widget = TargetListWidget()
    test_targets = [
        TargetItem(name="msedgewebview2d", enabled=True),
        TargetItem(name="spotify", enabled=False)
    ]
    widget.set_targets(test_targets)

    # Add manual input
    added = []
    widget.target_added.connect(added.append)
    widget.input_target.setText("teams.exe")
    widget.btn_add.click()
    assert added == ["teams.exe"]
    assert widget.input_target.text() == ""  # cleared
