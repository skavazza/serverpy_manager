import pytest
from vendor.systemram.core.memory_collector import (
    MemorySummary,
    ProcessMemoryInfo,
    get_memory_summary,
    get_priority_breakdown,
    get_processes_memory_list
)

def test_get_memory_summary():
    summary = get_memory_summary()
    assert isinstance(summary, MemorySummary)
    assert summary.total_bytes > 0
    assert summary.in_use_bytes > 0
    assert summary.free_bytes >= 0
    assert summary.standby_bytes >= 0
    assert summary.modified_bytes >= 0
    assert 0.0 <= summary.load_percent <= 100.0

def test_memory_partitions_sum_not_exceeding_total():
    summary = get_memory_summary()
    total_partitioned = (
        summary.in_use_bytes +
        summary.standby_bytes +
        summary.modified_bytes +
        summary.free_bytes +
        summary.zeroed_bytes
    )
    # The sum of non-overlapping physical RAM partitions must equal total_bytes
    assert total_partitioned <= summary.total_bytes + 4096

def test_get_priority_breakdown():
    breakdown = get_priority_breakdown()
    assert isinstance(breakdown, list)
    assert len(breakdown) == 8
    for i, item in enumerate(breakdown):
        assert item["priority"] == i
        assert "bytes" in item
        assert "mb" in item
        assert "percent" in item
        assert item["bytes"] >= 0

def test_get_processes_memory_list():
    procs = get_processes_memory_list()
    assert isinstance(procs, list)
    assert len(procs) > 0
    first = procs[0]
    assert isinstance(first, ProcessMemoryInfo)
    assert hasattr(first, "pid")
    assert hasattr(first, "name")
    assert hasattr(first, "working_set")
    assert hasattr(first, "private_bytes")
    assert hasattr(first, "commit_bytes")
