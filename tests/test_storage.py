import json
import os
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QLineEdit
from src.core.storage import list_external_drives
from src.gui.i18n import InterfaceLanguage
from src.gui.storage import StoragePanel


class TestExternalDriveDiscovery(unittest.TestCase):
    def test_single_volume_and_missing_metadata(self):
        result = SimpleNamespace(returncode=0, stdout=json.dumps({
            'DriveLetter': 'e', 'FileSystemLabel': 'Cópias', 'Size': 4096,
            'SizeRemaining': None,
        }), stderr='')
        with patch('src.core.storage.is_windows_10_or_11', return_value=True), patch(
            'src.core.storage.subprocess.run', return_value=result,
        ):
            self.assertEqual(list_external_drives(), (True, [
                {'path': 'E:\\', 'label': 'Cópias', 'size': 4096, 'free': 0},
            ]))

    def test_empty_response_and_volumes_without_drive_letters(self):
        with patch('src.core.storage.is_windows_10_or_11', return_value=True), patch(
            'src.core.storage.subprocess.run',
        ) as run:
            for raw in ('', 'null', '[]', '[{"DriveLetter":null},{"DriveLetter":"invalid"}]'):
                run.return_value = SimpleNamespace(returncode=0, stdout=raw, stderr='')
                self.assertEqual(list_external_drives(), (True, []))

    def test_failures_are_distinct_from_empty_results(self):
        with patch('src.core.storage.is_windows_10_or_11', return_value=True), patch(
            'src.core.storage.subprocess.run',
        ) as run:
            run.return_value = SimpleNamespace(returncode=1, stdout='', stderr='Access denied')
            self.assertEqual(list_external_drives(), (False, 'Access denied'))
            run.side_effect = subprocess.TimeoutExpired('powershell.exe', 15)
            self.assertFalse(list_external_drives()[0])
            run.side_effect = None
            run.return_value = SimpleNamespace(returncode=0, stdout='invalid json', stderr='')
            self.assertFalse(list_external_drives()[0])

    def test_unsupported_os_does_not_launch_powershell(self):
        with patch('sys.platform', 'win32'), patch('src.core.storage.is_windows_10_or_11', return_value=False), patch(
            'src.core.storage.subprocess.run',
        ) as run:
            self.assertFalse(list_external_drives()[0])
            run.assert_not_called()

    def test_linux_external_drive_discovery(self):
        with patch('sys.platform', 'linux'), patch('src.core.storage.is_windows_10_or_11', return_value=False):
            ok, drives = list_external_drives()
            self.assertTrue(ok)
            self.assertIsInstance(drives, list)



class TestStoragePanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = SimpleNamespace(
            language=InterfaceLanguage('pt'), windows_share_supported=True,
            server_manager=SimpleNamespace(is_running=False),
            window=SimpleNamespace(line_root_folder=QLineEdit()),
            navigation=SimpleNamespace(tabs=MagicMock()),
            save_server_preferences=MagicMock(), share_folder=MagicMock(),
        )
        self.panel = StoragePanel(self.controller)
        self.addCleanup(self.panel.close)
        self.drives = [{'path': 'E:\\', 'label': 'KINGSTON', 'size': 16 * 1024**3, 'free': 2 * 1024**3}]

    def select_drive(self):
        self.panel.scan_finished(True, self.drives)
        self.panel.table.selectRow(0)

    def test_share_opens_configuration_for_selected_drive(self):
        self.assertFalse(self.panel.share_button.isEnabled())
        self.select_drive()
        self.assertEqual(self.panel.table.horizontalHeaderItem(0).text(), 'Unidade')
        with patch('src.gui.storage.os.path.isdir', return_value=True):
            self.panel.share_button.click()
        self.controller.share_folder.assert_called_once_with('E:\\')

    def test_http_selection_and_running_server_guard(self):
        self.select_drive()
        with patch('src.gui.storage.os.path.isdir', return_value=True):
            self.panel.http_button.click()
        self.assertEqual(self.controller.window.line_root_folder.text(), 'E:\\')
        self.controller.save_server_preferences.assert_called_once()
        self.controller.navigation.tabs.setCurrentIndex.assert_called_once_with(0)
        self.controller.server_manager.is_running = True
        self.panel.update_actions()
        self.assertFalse(self.panel.http_button.isEnabled())
        self.assertTrue(self.panel.share_button.isEnabled())
        self.panel.use_in_http()
        self.controller.save_server_preferences.assert_called_once()

    def test_unplugged_drive_never_shares_a_fallback_folder(self):
        self.select_drive()
        with patch('src.gui.storage.os.path.isdir', return_value=False):
            self.panel.share_selected()
        self.controller.share_folder.assert_not_called()
        self.assertFalse(self.panel.share_button.isEnabled())
        self.assertIn('não está mais disponível', self.panel.status.text())

    def test_refresh_runs_in_background_and_clears_stale_selection(self):
        self.select_drive()
        with patch('src.gui.storage.QThreadPool.globalInstance') as pool:
            self.panel.refresh()
            self.panel.refresh()
            pool.return_value.start.assert_called_once()
            self.assertTrue(self.panel.loading)
            self.assertFalse(self.panel.share_button.isEnabled())
            self.assertFalse(self.panel.refresh_button.isEnabled())
            self.panel.scan.signals.finished.emit(False, 'Access denied')
        self.assertFalse(self.panel.loading)
        self.assertTrue(self.panel.refresh_button.isEnabled())
        self.assertFalse(self.panel.share_button.isEnabled())
        self.assertIn('Access denied', self.panel.status.text())

    def test_language_switch_preserves_drive_selection_and_metadata(self):
        self.select_drive()
        self.controller.language.code = 'en'
        self.panel.retranslate()
        self.assertEqual(self.panel.selected_drive()['label'], 'KINGSTON')
        self.assertEqual(self.panel.table.horizontalHeaderItem(0).text(), 'Drive')
        self.assertEqual(self.panel.share_button.text(), 'Share files on Windows network')
        self.assertTrue(self.panel.share_button.isEnabled())

    def test_unsupported_platform_explains_disabled_actions(self):
        self.controller.windows_share_supported = False
        with patch('src.gui.storage.sys.platform', 'darwin'):
            self.panel.retranslate()
            self.assertFalse(self.panel.refresh_button.isEnabled())
            self.assertIn('Windows 10 ou 11', self.panel.status.text())
