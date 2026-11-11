import pytest
from vendor.systemram.core.privileges import is_admin, enable_privilege, enable_required_privileges

def test_is_admin_returns_bool():
    res = is_admin()
    assert isinstance(res, bool)

def test_enable_privilege_structure():
    res = enable_privilege("SeProfileSingleProcessPrivilege")
    assert isinstance(res, bool)

def test_enable_required_privileges():
    success, privs = enable_required_privileges()
    assert isinstance(success, bool)
    assert isinstance(privs, list)
    assert "SeProfileSingleProcessPrivilege" in privs
    assert "SeIncreaseQuotaPrivilege" in privs
