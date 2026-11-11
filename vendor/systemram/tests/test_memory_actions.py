import pytest
from vendor.systemram.core.memory_actions import (
    empty_working_sets,
    empty_system_working_set,
    empty_modified_page_list,
    empty_standby_list,
    empty_all
)

def test_empty_working_sets_contract():
    success, msg, count = empty_working_sets()
    assert isinstance(success, bool)
    assert isinstance(msg, str)
    assert isinstance(count, int)
    assert count >= 0

def test_empty_system_working_set_contract():
    success, msg = empty_system_working_set()
    assert isinstance(success, bool)
    assert isinstance(msg, str)

def test_empty_modified_page_list_contract():
    success, msg = empty_modified_page_list()
    assert isinstance(success, bool)
    assert isinstance(msg, str)

def test_empty_standby_list_contracts():
    success_all, msg_all = empty_standby_list(priority0_only=False)
    assert isinstance(success_all, bool)
    assert isinstance(msg_all, str)

    success_p0, msg_p0 = empty_standby_list(priority0_only=True)
    assert isinstance(success_p0, bool)
    assert isinstance(msg_p0, str)

def test_empty_all_contract():
    results = empty_all()
    assert isinstance(results, dict)
    assert "working_sets" in results
    assert "system_working_set" in results
    assert "modified_page_list" in results
    assert "standby_list" in results
