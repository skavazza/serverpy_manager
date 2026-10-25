import unittest
from unittest.mock import patch

from src.core.privilege import release_replaced_instance


class TestPrivilege(unittest.TestCase):
    def test_windows_startup_does_not_call_linux_identity_functions(self):
        with patch('src.core.privilege.sys.platform', 'win32'), patch(
            'src.core.privilege.os.geteuid', create=True,
            side_effect=AssertionError('Linux identity API called on Windows'),
        ):
            release_replaced_instance()
