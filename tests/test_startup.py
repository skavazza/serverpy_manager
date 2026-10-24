import unittest
from unittest.mock import MagicMock, patch

from src.core.startup import StartupRegistration


class TestStartupRegistration(unittest.TestCase):
    def setUp(self):
        self.startup = StartupRegistration()
        self.startup.supported = True
        self.registry = MagicMock()
        self.registry.REG_SZ = 1
        self.startup.registry = self.registry

    def test_enable_and_disable_only_own_value(self):
        with patch.object(self.startup, 'command', return_value='"pythonw.exe" "main.py" --autostart'):
            self.startup.set_enabled(True)
        self.registry.CreateKeyEx.assert_called_once_with(self.registry.HKEY_CURRENT_USER, self.startup.KEY, 0, self.registry.KEY_SET_VALUE)
        self.assertEqual(self.registry.SetValueEx.call_args.args[1:], (self.startup.VALUE, 0, 1, '"pythonw.exe" "main.py" --autostart'))
        self.startup.set_enabled(False)
        self.assertEqual(self.registry.DeleteValue.call_args.args[1], self.startup.VALUE)

    def test_read_compares_registered_command(self):
        with patch.object(self.startup, 'command', return_value='current-command'):
            self.registry.QueryValueEx.return_value = ('current-command', 1)
            self.assertTrue(self.startup.is_enabled())
            self.registry.QueryValueEx.return_value = ('old-location', 1)
            self.assertFalse(self.startup.is_enabled())

    def test_missing_registration_is_safe(self):
        self.registry.OpenKey.side_effect = FileNotFoundError
        self.assertFalse(self.startup.is_enabled())
        self.startup.set_enabled(False)

    def test_permissions_are_reported(self):
        self.registry.CreateKeyEx.side_effect = PermissionError('denied')
        with patch.object(self.startup, 'command', return_value='command'):
            with self.assertRaises(PermissionError):
                self.startup.set_enabled(True)

    def test_command_quotes_paths_and_uses_windowed_python(self):
        with patch('src.core.startup.sys.executable', 'C:/Python environment/python.exe'), patch('src.core.startup.Path.is_file', return_value=True):
            command = self.startup.command()
        self.assertIn('pythonw.exe"', command)
        self.assertIn('main.py', command)
        self.assertTrue(command.endswith('--autostart'))

    def test_missing_pythonw_and_long_paths_do_not_register(self):
        with patch('src.core.startup.Path.is_file', return_value=False):
            with self.assertRaises(OSError):
                self.startup.set_enabled(True)
        with patch('src.core.startup.sys.executable', 'C:/' + 'a' * 270 + '/python.exe'), patch('src.core.startup.Path.is_file', return_value=True):
            with self.assertRaises(OSError):
                self.startup.set_enabled(True)
        self.registry.SetValueEx.assert_not_called()

    def test_unsupported_platform(self):
        self.startup.supported = False
        self.assertFalse(self.startup.is_enabled())
        with self.assertRaises(OSError):
            self.startup.set_enabled(True)

    def test_linux_autostart_enable_and_disable(self):
        linux_startup = StartupRegistration()
        linux_startup.supported = True
        linux_startup.registry = None
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            test_desktop = Path(tmpdir) / 'serverpy.desktop'
            with patch.object(linux_startup, '_linux_desktop_path', return_value=test_desktop):
                self.assertFalse(linux_startup.is_enabled())
                linux_startup.set_enabled(True)
                self.assertTrue(test_desktop.is_file())
                self.assertTrue(linux_startup.is_enabled())
                content = test_desktop.read_text(encoding='utf-8')
                self.assertIn('[Desktop Entry]', content)
                self.assertIn('--autostart', content)

                linux_startup.set_enabled(False)
                self.assertFalse(test_desktop.is_file())
                self.assertFalse(linux_startup.is_enabled())


if __name__ == '__main__':
    unittest.main()
