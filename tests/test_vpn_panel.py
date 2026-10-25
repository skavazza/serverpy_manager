import os
from pathlib import Path
import sys
import time
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from src.core.vpn import generate_identity
from src.gui.i18n import InterfaceLanguage
from src.gui.vpn_panel import VPNPanel


class TestVPNPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.prompt = patch(
            'src.gui.vpn_panel.QMessageBox.question',
            return_value=QMessageBox.No,
        )
        self.prompt.start()
        self.addCleanup(self.prompt.stop)
        self.controller = SimpleNamespace(language=InterfaceLanguage('pt'))
        self.panel = VPNPanel(self.controller, directory=self.temp.name)
        self.addCleanup(self.panel.close)
        self.addCleanup(self.panel.shutdown)

    def wait(self):
        for _ in range(500):
            if not self.panel.busy:
                return
            QTest.qWait(10)
            time.sleep(0.005)  # Release Python's GIL for QRunnable work.
        self.fail('VPN worker did not finish')

    def test_empty_diagnostics_never_creates_data_or_claims_connection(self):
        self.panel.refresh()
        self.wait()
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])
        self.assertIsNone(self.panel.registry)
        self.assertFalse(self.panel.buttons['Generate local invitation'].isEnabled())
        expected = 'instalação oficial' if sys.platform == 'win32' else 'privilégios administrativos'
        self.assertIn(expected, self.panel.note.text())

    def test_panel_separates_create_and_connect_modes(self):
        self.assertEqual(self.panel.mode_tabs.count(), 2)
        self.assertEqual(self.panel.mode_tabs.tabText(0), 'Criar uma rede')
        self.assertEqual(self.panel.mode_tabs.tabText(1), 'Conectar a uma rede')
        self.assertEqual(self.panel.enrollment_group.title(), 'Convidar e aprovar dispositivos')
        self.assertEqual(self.panel.client_tunnel_group.title(), 'Conectar a uma rede existente')
        self.assertIs(self.panel.buttons['Start WireGuard server'].parentWidget(), self.panel.tunnel_group)
        self.assertIs(self.panel.buttons['Connect WireGuard client'].parentWidget(), self.panel.client_tunnel_group)

    def test_create_mode_explains_next_step_after_empty_server_start(self):
        self.panel.tunnel_role = 'server'
        self.panel.tunnel_status = {'service_running': True, 'handshake_verified': False}
        self.panel.retranslate()
        self.assertIn('ainda não há dispositivo aprovado', self.panel.guide.text())
        self.assertIn('reinicie o túnel', self.panel.guide.text())

    def test_invalid_network_is_rejected_without_writes(self):
        self.panel.cidr.setText('0.0.0.0/0')
        self.panel.prepare()
        self.assertFalse(self.panel.busy)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])
        self.assertIn('IPv4 privada', self.panel.status.text())

    def test_review_rejects_invalid_invitation_without_network_or_writes(self):
        with patch('src.gui.vpn_panel.QInputDialog.getMultiLineText', return_value=('invalid-secret', True)), patch('src.core.vpn_enrollment.http.client.HTTPSConnection') as connection:
            self.panel.review_invite()
        connection.assert_not_called()
        self.assertIn('inválido ou expirado', self.panel.status.text())
        self.assertNotIn('invalid-secret', self.panel.status.text())
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    @unittest.skipUnless(sys.platform == 'win32', 'Requires Windows DPAPI')
    def test_prepare_invite_approve_revoke_and_reload(self):
        self.panel.prepare()
        self.wait()
        self.assertIsNotNone(self.panel.registry)
        self.assertFalse(self.panel.cidr.isEnabled())
        self.assertIn('não está ativa', self.panel.status.text())
        with patch.object(self.panel, 'show_invite') as dialog:
            self.panel.invite()
            self.wait()
            invitation = dialog.call_args.args[0]
        key = generate_identity().public_key
        self.panel.registry.request_admission(invitation.token, key, 'Notebook')
        self.panel.refresh()
        self.wait()
        self.panel.table.selectRow(0)
        self.assertTrue(self.panel.buttons['Approve device locally'].isEnabled())
        self.panel.change_device('approve')
        self.wait()
        self.assertEqual(self.panel.table.item(0, 2).text(), '10.77.0.2')
        self.panel.table.selectRow(0)
        self.panel.change_device('revoke')
        self.wait()
        self.assertEqual(self.panel.registry.authorized_peers(), ())
        self.panel.refresh()
        self.wait()
        self.assertEqual(self.panel.table.item(0, 1).text(), 'Revogado')
        self.controller.language = InterfaceLanguage('en')
        self.panel.retranslate()
        self.assertEqual(self.panel.buttons['Generate local invitation'].text(), 'Generate local invitation')

    def test_worker_error_is_reported_without_exposing_exception(self):
        with patch.object(self.panel, '_open', side_effect=ValueError('sensitive-test-token')):
            self.panel.refresh()
            self.wait()
        self.assertNotIn('sensitive-test-token', self.panel.status.text())
        self.assertIn('permissões', self.panel.status.text())
        self.assertTrue(self.panel.buttons['Refresh VPN status'].isEnabled())

    def test_missing_wireguard_offers_install_and_requires_confirmation(self):
        with (
            patch('src.gui.vpn_panel.wireguard_install_supported', return_value=True),
            patch.object(self.panel, '_run') as run,
            patch(
                'src.gui.vpn_panel.QMessageBox.question',
                return_value=QMessageBox.Yes,
            ) as prompt,
        ):
            self.panel.diagnostics = {'binaries_found': False}
            self.panel.update_actions()
            self.panel._offer_wireguard_install()
        self.assertTrue(self.panel.install_wireguard_button.isEnabled())
        prompt.assert_called_once()
        self.assertTrue(run.called)
        self.assertEqual(run.call_args.args[1], 'wireguard_install')
        self.assertTrue(self.panel.wireguard_install_prompted)

    def test_refresh_automatically_prompts_when_wireguard_is_missing(self):
        with (
            patch('src.gui.vpn_panel.wireguard_install_supported', return_value=True),
            patch.object(self.panel, '_run') as run,
            patch(
                'src.gui.vpn_panel.QMessageBox.question',
                return_value=QMessageBox.Yes,
            ) as prompt,
        ):
            self.panel.kind = 'refresh'
            self.panel._finished((None, [], {'binaries_found': False}, None), '')
        prompt.assert_called_once()
        self.assertEqual(run.call_args.args[1], 'wireguard_install')

    def test_declining_wireguard_install_does_not_start_download(self):
        with (
            patch('src.gui.vpn_panel.wireguard_install_supported', return_value=True),
            patch.object(self.panel, '_run') as run,
            patch(
                'src.gui.vpn_panel.QMessageBox.question',
                return_value=QMessageBox.No,
            ),
        ):
            self.panel.diagnostics = {'binaries_found': False}
            self.panel.install_wireguard()
        run.assert_not_called()

    @unittest.skipUnless(sys.platform == 'win32', 'Requires Windows DPAPI')
    def test_two_panels_enroll_over_real_https_and_stop_listener(self):
        from tests import test_vpn_enrollment as fixtures
        fixtures.TestVPNEnrollment.setUpClass()
        cert = Path(self.temp.name) / 'certificate.pem'
        key = Path(self.temp.name) / 'tls-key.pem'
        cert.write_text(fixtures.TestVPNEnrollment.pem, encoding='ascii')
        key.write_bytes(fixtures.TestVPNEnrollment.key_pem)
        self.panel.prepare()
        self.wait()
        with patch('src.gui.vpn_panel.QFileDialog.getOpenFileName', side_effect=[(str(cert), ''), (str(key), '')]), patch('src.gui.vpn_panel.QInputDialog.getText', return_value=('127.0.0.1', True)), patch('src.gui.vpn_panel.QInputDialog.getInt', return_value=(0, True)):
            self.panel.start_enrollment()
            self.wait()
        self.assertIsNotNone(self.panel.listener)
        self.assertTrue(self.panel.buttons['Generate remote invitation'].isEnabled())
        with patch('src.gui.vpn_panel.QInputDialog.getText', return_value=('127.0.0.1', True)), patch.object(self.panel, 'show_invite') as dialog:
            self.panel.remote_invite()
            self.wait()
            invite = dialog.call_args.args[0]
        client = VPNPanel(self.controller, directory=Path(self.temp.name) / 'client')
        self.addCleanup(client.close)
        self.addCleanup(client.shutdown)
        with patch('src.gui.vpn_panel.QInputDialog.getMultiLineText', return_value=(invite.export(), True)), patch('src.gui.vpn_panel.QInputDialog.getText', return_value=('Notebook remoto', True)):
            client.send_request()
            for _ in range(500):
                if not client.busy:
                    break
                QTest.qWait(10)
                time.sleep(0.005)
        self.assertFalse(client.busy)
        self.assertIn('Pedido de cadastro enviado', client.status.text())
        self.panel.refresh()
        self.wait()
        self.assertEqual(self.panel.table.item(0, 0).text(), 'Notebook remoto')
        self.assertEqual(self.panel.registry.authorized_peers(), ())
        self.panel.table.selectRow(0)
        self.panel.change_device('approve')
        self.wait()
        self.assertEqual(len(self.panel.registry.authorized_peers()), 1)
        self.panel.stop_enrollment()
        self.wait()
        self.assertIsNone(self.panel.listener)

    @unittest.skipUnless(sys.platform == 'win32', 'Requires Windows DPAPI')
    def test_wireguard_server_controls_and_revocation_stop_active_service(self):
        from tests.test_wireguard_windows import FakeWireGuard
        runtime = FakeWireGuard(self.temp.name)
        self.panel.prepare()
        self.wait()
        invite = self.panel.registry.create_invite()
        device = self.panel.registry.request_admission(invite.token, generate_identity().public_key, 'Notebook')
        self.panel.registry.approve(device)
        with patch('src.gui.vpn_panel.tunnel_backend', return_value=runtime), patch('src.gui.vpn_panel.QInputDialog.getInt', return_value=(51820, True)), patch('src.core.wireguard_windows.existing_routes', return_value=()), patch('src.core.wireguard_windows._powershell'):
            self.panel.start_wireguard_server()
            self.wait()
        self.assertEqual(self.panel.tunnel_role, 'server')
        self.assertTrue(self.panel.buttons['Disconnect WireGuard'].isEnabled())
        self.assertIn('aguardando handshake', self.panel.tunnel_label.text())
        self.panel.refresh()
        self.wait()
        self.panel.table.selectRow(0)
        self.panel.change_device('revoke')
        self.wait()
        self.assertEqual(runtime.states, {})
        self.assertIsNone(self.panel.tunnel_name)
        self.assertEqual(self.panel.registry.authorized_peers(), ())

    @unittest.skipUnless(sys.platform == 'win32', 'Requires Windows DPAPI')
    def test_wireguard_prerequisite_error_is_translated(self):
        from src.core.wireguard_windows import WireGuardError
        self.panel.prepare()
        self.wait()
        with patch('src.gui.vpn_panel.tunnel_backend', side_effect=WireGuardError('Run ServerPy as administrator to manage WireGuard tunnels.')), patch('src.gui.vpn_panel.QInputDialog.getInt', return_value=(51820, True)):
            self.panel.start_wireguard_server()
            self.wait()
        self.assertIn('administrador', self.panel.status.text())
        self.assertIsNone(self.panel.tunnel_name)


if __name__ == '__main__':
    unittest.main()
