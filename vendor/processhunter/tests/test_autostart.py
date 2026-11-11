import winreg
from unittest.mock import MagicMock, patch
import pytest
from vendor.processhunter.core.autostart import WindowsAutostart


def test_autostart_is_enabled_true():
    mock_key = MagicMock()
    with patch("winreg.OpenKey", return_value=mock_key), \
         patch("winreg.QueryValueEx", return_value=('"C:\\python.exe" "C:\\app.py" --minimized', winreg.REG_SZ)):
        manager = WindowsAutostart(app_name="ProcessHunterTest")
        assert manager.is_enabled() is True


def test_autostart_is_enabled_false():
    with patch("winreg.OpenKey", side_effect=FileNotFoundError):
        manager = WindowsAutostart(app_name="ProcessHunterTest")
        assert manager.is_enabled() is False


def test_autostart_enable():
    mock_key = MagicMock()
    with patch("winreg.OpenKey", return_value=mock_key) as mock_open, \
         patch("winreg.SetValueEx") as mock_set:
        manager = WindowsAutostart(app_name="ProcessHunterTest")
        success = manager.enable(
            entrypoint_path=r"C:\Scripts\processhunter\app.py",
            python_exe=r"C:\Python\pythonw.exe",
            start_minimized=True
        )

        assert success is True
        mock_set.assert_called_once()
        args = mock_set.call_args[0]
        assert args[1] == "ProcessHunterTest"
        assert args[2] == 0
        assert args[3] == winreg.REG_SZ
        assert args[4] == r'"C:\Python\pythonw.exe" "C:\Scripts\processhunter\app.py" --minimized'


def test_autostart_disable_success():
    mock_key = MagicMock()
    mock_key.__enter__.return_value = mock_key
    with patch("winreg.OpenKey", return_value=mock_key), \
         patch("winreg.DeleteValue") as mock_del:
        manager = WindowsAutostart(app_name="ProcessHunterTest")
        success = manager.disable()

        assert success is True
        mock_del.assert_called_once_with(mock_key, "ProcessHunterTest")


def test_autostart_disable_already_disabled():
    mock_key = MagicMock()
    with patch("winreg.OpenKey", return_value=mock_key), \
         patch("winreg.DeleteValue", side_effect=FileNotFoundError):
        manager = WindowsAutostart(app_name="ProcessHunterTest")
        success = manager.disable()

        # Should handle gracefully and return True
        assert success is True
