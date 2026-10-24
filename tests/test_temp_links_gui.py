import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QComboBox
from src.core.explorer import FileExplorer
from src.core.temp_links import TemporaryLinks, DOWNLOAD_PREFIX
from src.gui.i18n import InterfaceLanguage
from src.gui.temp_links import CreateLinkDialog, TemporaryLinksPanel


class TestTemporaryLinksGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file = self.root / 'document.txt'
        self.file.write_text('download')
        self.explorer = FileExplorer(self.root)
        access = QComboBox()
        access.addItem('http://192.0.2.1:8080', 'http://192.0.2.1:8080')
        self.controller = SimpleNamespace(app=self.app, language=InterfaceLanguage('pt'),
            server_manager=SimpleNamespace(links=TemporaryLinks(), is_running=True,
                httpd=SimpleNamespace(explorer=self.explorer, shared_explorers={})),
            access_combo=access, show_qr_code=MagicMock())

    def test_dialog_creates_password_link_and_clears_password(self):
        dialog = CreateLinkDialog(self.controller)
        self.addCleanup(dialog.close)
        dialog.filename.setText(str(self.file))
        dialog.require_password.setChecked(True)
        dialog.accept()
        self.assertEqual(dialog.result(), 0)
        self.assertIn('senha', dialog.error.text())
        dialog.password.setText('only-link-password')
        dialog.accept()
        self.assertEqual(dialog.result(), 1)
        self.assertEqual(dialog.password.text(), '')
        self.assertTrue(self.controller.server_manager.links.info(dialog.token)['protected'])

    def test_old_dialog_cannot_grant_files_after_session_changes(self):
        dialog = CreateLinkDialog(self.controller)
        self.addCleanup(dialog.close)
        dialog.filename.setText(str(self.file))
        self.controller.server_manager.links = TemporaryLinks()
        dialog.accept()
        self.assertEqual(dialog.result(), 0)
        self.assertEqual(self.controller.server_manager.links.snapshot(), [])
        self.assertIn('sessão', dialog.error.text())

    def test_copy_qr_revoke_and_language_preserve_selected_link(self):
        token = self.controller.server_manager.links.create(self.explorer, self.file)
        panel = TemporaryLinksPanel(self.controller)
        self.addCleanup(panel.close)
        panel.refresh(token)
        self.assertTrue(panel.copy_button.isEnabled())
        panel.copy_button.click()
        url = 'http://192.0.2.1:8080' + DOWNLOAD_PREFIX + token
        self.assertEqual(self.app.clipboard().text(), url)
        panel.qr_button.click()
        self.controller.show_qr_code.assert_called_once_with(url, temporary=True)
        self.controller.language.code = 'en'
        panel.retranslate()
        self.assertEqual(panel.selected_token(), token)
        self.assertEqual(panel.table.item(0, 4).text(), 'Valid')
        panel.revoke_button.click()
        self.assertFalse(panel.copy_button.isEnabled())
        self.assertFalse(panel.qr_button.isEnabled())
        self.assertEqual(panel.table.item(0, 4).text(), 'Revoked')
        self.controller.server_manager.links.clear()
        self.controller.server_manager.is_running = False
        panel.refresh()
        self.assertFalse(panel.create_button.isEnabled())
        self.assertEqual(panel.table.rowCount(), 0)
