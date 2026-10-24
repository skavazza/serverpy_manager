import os
from types import SimpleNamespace
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from src.core.traffic import TrafficMonitor
from src.gui.activity import ActivityPanel
from src.gui.i18n import InterfaceLanguage


class TestActivityPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.monitor = TrafficMonitor()
        self.controller = SimpleNamespace(language=InterfaceLanguage('pt'),
            server_manager=SimpleNamespace(traffic=self.monitor, is_running=True))
        self.panel = ActivityPanel(self.controller)
        self.addCleanup(self.panel.close)

    def add_request(self, path, active=False):
        token = self.monitor.open_connection('192.0.2.8')
        self.monitor.begin_cycle(token)
        self.monitor.start_request(token, 'GET', path)
        self.monitor.add_bytes(token, 'sent', 2048)
        self.monitor.set_status(token, 200)
        if not active:
            self.monitor.close_connection(token)
        return token

    def test_live_rows_filtering_and_translation(self):
        token = self.add_request('/_shares/docs/report.pdf?token=secret', active=True)
        self.add_request('/api/ping')
        self.panel.refresh()
        self.assertEqual(self.panel.clients.rowCount(), 1)
        self.assertEqual(self.panel.clients.item(0, 0).text(), '192.0.2.8')
        self.assertEqual(self.panel.requests.rowCount(), 1)
        self.assertEqual(self.panel.requests.item(0, 2).text(), '/_shares/docs/report.pdf')
        self.assertIn('Em andamento', self.panel.requests.item(0, 3).text())
        self.assertIn('Clientes ativos: 1', self.panel.summary.text())
        self.panel.hide_background.setChecked(False)
        self.assertEqual(self.panel.requests.rowCount(), 2)
        self.controller.language.code = 'en'
        self.panel.retranslate()
        self.assertIn('In progress', self.panel.requests.item(0, 3).text())
        self.assertEqual(self.panel.clients.horizontalHeaderItem(0).text(), 'IP address')
        self.assertFalse(self.panel.hide_background.isChecked())
        self.monitor.close_connection(token)
        self.controller.server_manager.is_running = False
        self.panel.refresh()
        self.assertIn('stopped', self.panel.state.text())
        self.assertEqual(self.panel.requests.rowCount(), 2)
        self.assertIn('Completed', self.panel.requests.item(0, 3).text())

    def test_auto_refresh_runs_only_while_visible(self):
        self.assertFalse(self.panel.timer.isActive())
        self.panel.show()
        self.app.processEvents()
        self.assertTrue(self.panel.timer.isActive())
        self.panel.hide()
        self.app.processEvents()
        self.assertFalse(self.panel.timer.isActive())
