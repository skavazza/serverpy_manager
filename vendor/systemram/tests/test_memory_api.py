import pytest
from vendor.systemram.core.memory_api import (
    query_global_memory_status,
    query_performance_info,
    query_system_memory_list_info,
    SYSTEM_MEMORY_LIST_COMMAND,
    SYSTEM_MEMORY_LIST_INFORMATION,
    set_system_memory_list,
    set_system_filecache
)

def test_query_global_memory_status():
    mem = query_global_memory_status()
    assert mem.ullTotalPhys > 0
    assert mem.ullAvailPhys > 0
    assert 0 <= mem.dwMemoryLoad <= 100

def test_query_performance_info():
    perf = query_performance_info()
    assert perf.PhysicalTotal > 0
    assert perf.PageSize > 0
    assert perf.PhysicalAvailable > 0

def test_query_system_memory_list_info():
    info = query_system_memory_list_info()
    assert isinstance(info, SYSTEM_MEMORY_LIST_INFORMATION)
    assert info.ZeroPageCount >= 0
    assert info.FreePageCount >= 0
    assert len(info.PageCountByPriority) == 8

def test_system_memory_list_commands_enum():
    assert SYSTEM_MEMORY_LIST_COMMAND.MemoryEmptyWorkingSets == 0
    assert SYSTEM_MEMORY_LIST_COMMAND.MemoryFlushModifiedList == 1
    assert SYSTEM_MEMORY_LIST_COMMAND.MemoryPurgeStandbyList == 2
    assert SYSTEM_MEMORY_LIST_COMMAND.MemoryPurgeLowPriorityStandbyList == 3

def test_ctypes_signatures_and_struct_size():
    import ctypes
    from vendor.systemram.core.memory_api import kernel32, psapi
    assert ctypes.sizeof(SYSTEM_MEMORY_LIST_INFORMATION) == 176
    assert hasattr(kernel32.SetProcessWorkingSetSize, "argtypes") and kernel32.SetProcessWorkingSetSize.argtypes is not None
    assert hasattr(kernel32.OpenProcess, "argtypes") and kernel32.OpenProcess.argtypes is not None
    assert hasattr(psapi.EmptyWorkingSet, "argtypes") and psapi.EmptyWorkingSet.argtypes is not None
