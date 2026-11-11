import pytest
from PySide6.QtWidgets import QApplication
from vendor.systemram.gui.tab_use_counts import TabUseCounts
from vendor.systemram.gui.tab_processes import TabProcesses
from vendor.systemram.gui.tab_priority import TabPriority
from vendor.systemram.core.memory_collector import get_memory_summary, get_priority_breakdown, get_processes_memory_list

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

def test_tabs_initialization(qapp):
    t1 = TabUseCounts()
    t2 = TabProcesses()
    t3 = TabPriority()
    assert t1 is not None
    assert t2 is not None
    assert t3 is not None

def test_tabs_update_data(qapp):
    t1 = TabUseCounts()
    t2 = TabProcesses()
    t3 = TabPriority()

    summary = get_memory_summary()
    t1.update_data(summary)
    assert t1.table.rowCount() > 0

    procs = get_processes_memory_list()[:10]
    t2.update_data(procs)
    assert t2.table.rowCount() == len(procs)

    priorities = get_priority_breakdown()
    t3.update_data(priorities)
    assert t3.table.rowCount() == 8
