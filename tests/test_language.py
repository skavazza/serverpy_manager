import os
import sys
import tempfile
import unittest
import socket
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtCore import QTime
from PySide6.QtWidgets import QDialogButtonBox
from src.gui.controller import AppController
from src.gui.dialogs import CORSDialog, RedirectionDialog, ResponseHeadersDialog, AboutDialog


class TestInterfaceLanguage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_streams = sys.stdout, sys.stderr
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="serverpy_language_")
        cls.settings = QSettings(os.path.join(cls.temp_dir.name, "settings.ini"), QSettings.IniFormat)
        cls.settings.setValue("interface_language", "pt")
        cls.startup = MagicMock(supported=True)
        cls.startup.is_enabled.return_value = False
        with patch("src.gui.controller.QSettings", return_value=cls.settings), patch('src.gui.controller.StartupRegistration', return_value=cls.startup):
            cls.controller = AppController()
        sys.stdout, sys.stderr = cls.original_streams

    @classmethod
    def tearDownClass(cls):
        cls.controller.schedule_timer.stop()
        cls.controller.server_manager.stop_server()
        cls.controller.window.close()
        cls.controller.log_window.close()
        cls.temp_dir.cleanup()
        sys.stdout, sys.stderr = cls.original_streams

    def setUp(self):
        controller = self.controller
        controller.restoring_preferences = True
        for name in controller.PERSISTED_CHECKS:
            getattr(controller.window, name).setChecked(name in ('chk_render_pages', 'chk_allow_mod'))
        controller.window.line_port.setText('0')
        controller.window.line_root_folder.setText(self.temp_dir.name)
        controller.window.line_cloudflare_hostname.setText('')
        controller.window.combo_interface.setCurrentIndex(1)
        controller.navigation.actions['language_pt'].trigger()
        controller.restoring_preferences = False
        controller.validate_inputs()

    def test_about_dialog_shows_developer_and_contacts_in_both_languages(self):
        controller = self.controller
        dialog = AboutDialog(controller.window, controller.language)
        self.assertEqual(dialog.windowTitle(), 'Sobre')
        self.assertEqual(dialog.fields['developer'].text(), 'KrakenTech Services')
        self.assertIn('mailto:krakensrvc@gmail.com', dialog.fields['email'].text())
        self.assertIn('https://wa.me/5511992748645', dialog.fields['whatsapp'].text())
        self.assertEqual(dialog.fields['license'].text(), 'Somente uso pessoal (não comercial)')
        self.assertIn('LICENÇA PARA USO PESSOAL', dialog.license_text.toPlainText())
        self.assertEqual(controller.navigation.actions['about'].text(), 'Sobre')
        controller.navigation.actions['language_en'].trigger()
        self.assertEqual(controller.navigation.actions['about'].text(), 'About')
        english = AboutDialog(controller.window, controller.language)
        self.assertEqual(english.windowTitle(), 'About')
        self.assertEqual(english.fields['license'].text(), 'Personal use only (non-commercial)')
        self.assertEqual(english.fields['developer'].text(), 'KrakenTech Services')
        controller.navigation.actions['language_pt'].trigger()

    def test_toolbar_uses_live_menu_actions_and_translated_accessible_names(self):
        controller = self.controller
        navigation = controller.navigation
        toolbar = navigation.toolbar
        self.assertFalse(hasattr(controller, 'language_combo'))
        self.assertFalse(hasattr(controller, 'about_button'))
        for key in ('start', 'stop', 'logs', 'copy', 'open', 'qr', 'about'):
            action = navigation.actions[key]
            button = toolbar.widgetForAction(action)
            self.assertIs(button.defaultAction(), action)
            self.assertFalse(action.icon().isNull())
            self.assertEqual(button.accessibleName(), action.text())
        self.assertFalse(navigation.actions['stop'].isEnabled())
        self.assertFalse(navigation.actions['qr'].isEnabled())
        toolbar.widgetForAction(navigation.actions['start']).click()
        try:
            self.assertTrue(controller.server_manager.is_running)
            self.assertFalse(navigation.actions['start'].isEnabled())
            self.assertTrue(navigation.actions['stop'].isEnabled())
            self.assertTrue(navigation.actions['qr'].isEnabled())
            navigation.actions['language_en'].trigger()
            self.assertEqual(toolbar.widgetForAction(navigation.actions['copy']).accessibleName(), 'Copy URL')
            with patch('src.gui.controller.AboutDialog') as dialog:
                toolbar.widgetForAction(navigation.actions['about']).click()
                dialog.return_value.exec.assert_called_once()
            toolbar.widgetForAction(navigation.actions['stop']).click()
            self.assertFalse(controller.server_manager.is_running)
            self.assertTrue(navigation.actions['start'].isEnabled())
            self.assertFalse(navigation.actions['copy'].isEnabled())
        finally:
            if controller.server_manager.is_running:
                controller._stop_server()

    def test_tabs_and_menu_navigation_preserve_configuration_and_language(self):
        controller = self.controller
        navigation = controller.navigation
        tabs = navigation.tabs
        self.assertEqual(tabs.count(), 10)
        self.assertEqual(navigation.network_tabs.count(), 5)
        self.assertIs(navigation.network_tabs.widget(2), navigation.ssh)
        self.assertEqual(navigation.network_tabs.tabText(2), 'SSH')
        for panel in (navigation.activity, navigation.network, navigation.ssh):
            margins = panel.layout().contentsMargins()
            self.assertEqual((margins.left(), margins.top(), margins.right(), margins.bottom()), (8, 8, 8, 8))
        self.assertIs(navigation.network_tabs.widget(3), navigation.findport)
        self.assertEqual(navigation.network_tabs.tabText(3), 'FindPort')
        self.assertIs(navigation.network_tabs.widget(4), navigation.transfers)
        self.assertEqual(navigation.network_tabs.tabText(4), 'Transferências')
        self.assertEqual(tabs.tabText(0), 'Servidor')
        self.assertEqual(tabs.tabText(4), 'Câmeras')
        folder = controller.window.line_root_folder.text()
        navigation.actions['tab_1'].trigger()
        self.assertEqual(tabs.currentIndex(), 1)
        self.assertTrue(navigation.pages['Files'].isAncestorOf(controller.window.line_root_folder))
        self.assertTrue(navigation.pages['Printers'].isAncestorOf(controller.window.btn_share_printers))
        self.assertTrue(navigation.pages['Security'].isAncestorOf(controller.window.chk_auth))
        self.assertTrue(navigation.pages['Settings'].isAncestorOf(controller.headers_button))
        for button in navigation.pending_buttons:
            self.assertFalse(button.isEnabled())
        navigation.actions['language_en'].trigger()
        self.assertEqual(tabs.tabText(0), 'Server')
        self.assertEqual(navigation.menus['Application'].title(), 'Application')
        self.assertEqual(controller.window.line_root_folder.text(), folder)
        self.assertEqual(tabs.currentIndex(), 1)
        navigation.actions['language_pt'].trigger()
        self.assertEqual(navigation.menus['Application'].title(), 'Aplicativo')
        self.assertEqual(tabs.tabText(8), 'Configurações')
        self.assertEqual(tabs.tabText(6), 'Android')
        self.assertIs(navigation.android.parentWidget(), navigation.pages['Android'])
        tabs.setCurrentIndex(0)

    def test_server_menu_tracks_validation_and_server_state(self):
        controller = self.controller
        actions = controller.navigation.actions
        controller.window.line_port.setText('invalid')
        self.assertFalse(actions['start'].isEnabled())
        self.assertFalse(actions['stop'].isEnabled())
        controller.window.line_port.setText('0')
        self.assertTrue(actions['start'].isEnabled())
        try:
            actions['start'].trigger()
            self.assertTrue(controller.server_manager.is_running)
            self.assertFalse(actions['start'].isEnabled())
            self.assertTrue(actions['stop'].isEnabled())
            self.assertTrue(actions['open'].isEnabled())
            actions['stop'].trigger()
            self.assertFalse(controller.server_manager.is_running)
            self.assertFalse(actions['stop'].isEnabled())
            self.assertFalse(actions['open'].isEnabled())
        finally:
            if controller.server_manager.is_running:
                controller._stop_server()

    def test_shared_folders_persist_and_qr_follows_running_server(self):
        controller = self.controller
        original = controller.shared_folders
        try:
            controller.shared_folders = [{'name': 'docs', 'path': self.temp_dir.name, 'writable': False}]
            controller.navigation.shared_folders.reload()
            controller.save_server_preferences()
            controller.shared_folders = []
            controller.restore_server_preferences()
            self.assertEqual(controller.shared_folders[0]['name'], 'docs')
            self.assertFalse(controller.shared_folders[0]['writable'])
            panel = controller.navigation.shared_folders
            panel.table.selectRow(0)
            self.assertFalse(controller.qr_button.isEnabled())
            controller._start_server()
            self.assertTrue(controller.server_manager.is_running)
            self.assertTrue(controller.qr_button.isEnabled())
            self.assertFalse(panel.add_button.isEnabled())
            self.assertTrue(panel.qr_button.isEnabled())
            url = controller.access_combo.currentData()
            with patch('src.gui.controller.QRCodeDialog') as dialog:
                panel.qr_button.click()
                dialog.assert_called_once_with(url + '/_shares/docs/', controller.window, controller.language)
                dialog.return_value.exec.assert_called_once()
            controller._stop_server()
            self.assertFalse(controller.qr_button.isEnabled())
            self.assertTrue(panel.add_button.isEnabled())
        finally:
            if controller.server_manager.is_running:
                controller._stop_server()
            controller.shared_folders = original
            controller.navigation.shared_folders.reload()
            controller.save_server_preferences()

    def test_network_diagnostics_runs_without_blocking_ui_and_translates_results(self):
        panel = self.controller.navigation.network
        panel.host.setText('127.0.0.1')
        with patch('src.gui.network_tools.QThreadPool.globalInstance') as pool:
            panel.run_button.click()
            self.assertFalse(panel.run_button.isEnabled())
            pool.return_value.start.assert_called_once()
            panel.task.signals.finished.emit([('Name resolution', 'OK', '127.0.0.1'), ('TCP connection', 'Failed', 'refused')])
        self.assertTrue(panel.run_button.isEnabled())
        self.assertEqual(panel.table.item(0, 0).text(), 'Resolução de nome')
        self.assertEqual(panel.table.item(1, 1).text(), 'Falhou')
        self.controller.navigation.actions['language_en'].trigger()
        self.assertEqual(panel.table.item(0, 0).text(), 'Name resolution')
        self.controller.navigation.actions['language_pt'].trigger()

    def test_custom_headers_dialog_validation_and_persistence(self):
        controller = self.controller
        self.assertEqual(controller.advanced_group.title(), 'Avançado')
        self.assertFalse(controller.headers_button.isEnabled())
        controller.window.chk_custom_headers.setChecked(True)
        self.assertTrue(controller.headers_button.isEnabled())
        self.assertTrue(controller.window.chk_custom_headers.isEnabled())
        controller.custom_headers = {'Cache-Control': 'no-store'}
        controller.save_server_preferences()
        controller.custom_headers = {}
        controller.restore_server_preferences()
        self.assertEqual(controller.custom_headers, {'Cache-Control': 'no-store'})
        dialog = ResponseHeadersDialog(controller.custom_headers, controller.window, controller.language)
        dialog.add_row('Content-Length', '100')
        dialog.accept()
        self.assertEqual(dialog.result(), 0)
        self.assertIn('gerenciado pelo servidor', dialog.error.text())
        dialog.table.removeRow(1)
        dialog.add_row('X-Content-Type-Options', 'nosniff')
        dialog.accept()
        self.assertEqual(dialog.result(), 1)
        self.assertEqual(dialog.get_headers()['X-Content-Type-Options'], 'nosniff')
        controller.navigation.actions['language_en'].trigger()
        self.assertEqual(controller.advanced_group.title(), 'Advanced')
        self.assertEqual(controller.headers_button.text(), 'Configure headers')
        controller.navigation.actions['language_pt'].trigger()
        controller.window.chk_custom_headers.setChecked(False)
        self.assertEqual(controller.custom_headers, {'Cache-Control': 'no-store'})

    def test_custom_headers_enable_and_disable_at_server_start(self):
        controller = self.controller
        controller.custom_headers = {'X-Test': 'configured'}
        try:
            controller.window.chk_custom_headers.setChecked(True)
            controller._start_server()
            self.assertEqual(controller.server_manager.httpd.app_config['custom_headers'], {'X-Test': 'configured'})
            controller._stop_server()
            controller.window.chk_custom_headers.setChecked(False)
            controller._start_server()
            self.assertEqual(controller.server_manager.httpd.app_config['custom_headers'], {})
        finally:
            controller._stop_server()

    def test_autostart_toggle_and_failure_rollback(self):
        controller = self.controller
        field = controller.window.chk_autostart
        self.assertTrue(field.isEnabled())
        self.assertNotIn('indisponível', field.text())
        self.startup.set_enabled.reset_mock()
        field.setChecked(True)
        self.startup.set_enabled.assert_called_once_with(True)
        self.assertTrue(controller.autostart_enabled)
        self.startup.set_enabled.side_effect = PermissionError('denied')
        try:
            with patch('src.gui.controller.QMessageBox.warning') as warning:
                field.setChecked(False)
                warning.assert_called_once()
            self.assertTrue(field.isChecked())
            self.assertTrue(controller.autostart_enabled)
        finally:
            self.startup.set_enabled.side_effect = None
            field.setChecked(False)
        self.startup.set_enabled.assert_called_with(False)

    def test_live_validation_and_translation(self):
        controller = self.controller
        window = controller.window
        for invalid in ('wrong', '-1', '65536'):
            window.line_port.setText(invalid)
            self.assertIn('line_port', controller.validation_errors)
            self.assertFalse(window.btn_start.isEnabled())
        window.line_port.setText('0')
        window.line_root_folder.setText(os.path.join(self.temp_dir.name, 'missing'))
        self.assertIn('line_root_folder', controller.validation_errors)
        controller.navigation.actions['language_en'].trigger()
        self.assertEqual(controller.field_errors['line_root_folder'].text(), 'Select an existing folder.')
        controller.navigation.actions['language_pt'].trigger()
        self.assertEqual(controller.field_errors['line_root_folder'].text(), 'Selecione uma pasta existente.')
        window.line_root_folder.setText(self.temp_dir.name)
        self.assertTrue(window.btn_start.isEnabled())
        window.chk_auth.setChecked(True)
        window.line_username.setText('')
        window.line_password.setText('')
        self.assertIn('line_username', controller.validation_errors)
        self.assertIn('line_password', controller.validation_errors)
        window.chk_auth.setChecked(False)
        window.chk_rate_limit.setChecked(True)
        window.line_rate_limit.setText('0')
        self.assertIn('line_rate_limit', controller.validation_errors)
        window.chk_rate_limit.setChecked(False)
        window.chk_whitelist.setChecked(True)
        window.line_whitelist.setText('999.1.1.1')
        self.assertIn('line_whitelist', controller.validation_errors)
        window.line_whitelist.setText('2001:db8::1')
        self.assertNotIn('line_whitelist', controller.validation_errors)
        window.chk_whitelist.setChecked(False)
        window.chk_cloudflare_tunnel.setChecked(True)
        window.line_cloudflare_hostname.setText('not a hostname')
        self.assertIn('line_cloudflare_hostname', controller.validation_errors)
        window.line_cloudflare_hostname.setText('arquivos.exemplo.com')
        self.assertNotIn('line_cloudflare_hostname', controller.validation_errors)
        window.chk_cloudflare_tunnel.setChecked(False)
        window.chk_custom_charset.setChecked(True)
        window.line_custom_charset.setText('not-an-encoding')
        self.assertIn('line_custom_charset', controller.validation_errors)

    def test_invalid_certificate_is_shown_before_start(self):
        controller = self.controller
        path = os.path.join(self.temp_dir.name, 'invalid.pem')
        with open(path, 'w') as file: file.write('invalid certificate')
        controller.cert_path = path
        controller.window.chk_tls.setChecked(True)
        self.assertIn('lbl_cert_info', controller.validation_errors)
        self.assertFalse(controller.window.btn_start.isEnabled())
        controller._start_server()
        self.assertFalse(controller.server_manager.is_running)
        controller.window.chk_tls.setChecked(False)

    def test_actual_port_urls_clipboard_and_browser(self):
        controller = self.controller
        controller.window.chk_verify_header.setChecked(True)
        controller._start_server()
        self.addCleanup(controller._stop_server)
        port = controller.server_manager.httpd.server_address[1]
        self.assertGreater(port, 0)
        self.assertEqual(controller.server_manager.httpd.app_config['port'], port)
        self.assertEqual(controller.access_combo.currentData(), f'http://127.0.0.1:{port}')
        controller.copy_access_url()
        self.assertEqual(controller.app.clipboard().text(), f'http://127.0.0.1:{port}')
        network = controller.navigation.network
        self.assertTrue(network.phone_qr_button.isEnabled())
        with patch.object(controller, 'show_qr_code') as show_qr:
            network.phone_qr_button.click()
            show_qr.assert_called_once_with(controller.access_combo.currentData())
        with patch('src.gui.controller.QDesktopServices.openUrl') as opened:
            controller.open_access_url()
            self.assertEqual(opened.call_args.args[0].toString(), f'http://127.0.0.1:{port}')

    def test_missing_folder_users_explains_how_to_fix_before_start(self):
        controller = self.controller
        controller.folder_users_enabled = True
        controller.folder_users = []
        controller.navigation.tabs.setCurrentIndex(0)
        controller._start_server()

        self.assertFalse(controller.server_manager.is_running)
        self.assertFalse(controller.start_error.isHidden())
        self.assertIn('Adicione pelo menos um usuário de pasta', controller.start_error.text())
        self.assertEqual(controller.navigation.tabs.currentIndex(), controller.navigation.TAB_TITLES.index('Security'))
        controller.folder_users_enabled = False

    def test_cloudflare_tunnel_settings_are_passed_to_server(self):
        controller = self.controller
        controller.window.chk_cloudflare_tunnel.setChecked(True)
        controller.window.line_cloudflare_hostname.setText('Files.Exämple.com')
        controller._start_server()
        self.addCleanup(controller._stop_server)
        config = controller.server_manager.httpd.app_config
        self.assertTrue(config['cloudflare_tunnel'])
        self.assertEqual(config['cloudflare_hostname'], 'files.xn--exmple-cua.com')

    def test_wildcard_addresses_are_real_and_inactive_before_start(self):
        controller = self.controller
        addresses = {'ethernet': [SimpleNamespace(family=socket.AF_INET, address='192.168.50.10')]}
        with patch('src.gui.controller.psutil.net_if_addrs', return_value=addresses):
            controller.window.line_port.setText('8080')
            controller.window.combo_interface.setCurrentIndex(0)
            controller.update_url()
        urls = [controller.access_combo.itemData(index) for index in range(controller.access_combo.count())]
        self.assertEqual(urls, ['http://127.0.0.1:8080', 'http://192.168.50.10:8080'])
        self.assertFalse(controller.open_url_button.isEnabled())
        self.assertTrue(controller.copy_url_button.isEnabled())

    def test_occupied_port_has_visible_feedback(self):
        controller = self.controller
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            controller.window.line_port.setText(str(occupied.getsockname()[1]))
            controller._start_server()
            self.assertFalse(controller.server_manager.is_running)
            self.assertFalse(controller.start_error.isHidden())
            self.assertIn('porta está em uso ou indisponível', controller.start_error.text())

    def test_extended_preferences_roundtrip(self):
        controller = self.controller
        controller.window.line_password.setText('never-store-this-password')
        controller.window.line_whitelist.setText('127.0.0.1')
        controller.window.chk_cloudflare_tunnel.setChecked(True)
        controller.window.line_cloudflare_hostname.setText('files.example.com')
        controller.window.line_rate_limit.setText('25')
        controller.window.time_start.setTime(QTime(9, 30))
        controller.window.time_stop.setTime(QTime(18, 0))
        controller.cors_config = {'origin': 'https://example.com', 'methods': 'GET', 'headers': 'Authorization'}
        controller.redirections = [('/old', '/new', 302)]
        controller.save_server_preferences()
        saved = self.settings.value('server/options')
        self.assertNotIn('never-store-this-password', saved)
        controller.restoring_preferences = True
        controller.window.line_rate_limit.setText('10')
        controller.window.chk_cloudflare_tunnel.setChecked(False)
        controller.window.line_cloudflare_hostname.setText('')
        controller.window.time_start.setTime(QTime(0, 0))
        controller.cors_config = {}
        controller.redirections = []
        controller.restoring_preferences = False
        controller.restore_server_preferences()
        self.assertEqual(controller.window.line_rate_limit.text(), '25')
        self.assertEqual(controller.window.time_start.time(), QTime(9, 30))
        self.assertEqual(controller.cors_config['origin'], 'https://example.com')
        self.assertEqual(controller.redirections, [('/old', '/new', 302)])
        self.assertTrue(controller.window.chk_cloudflare_tunnel.isChecked())
        self.assertEqual(controller.window.line_cloudflare_hostname.text(), 'files.example.com')

    def test_log_filters_export_and_fragmented_messages(self):
        log = self.controller.log_window
        log.clear_logs()
        log.category.setCurrentIndex(0)
        log.search.clear()
        log.append_log('Error: fragmented')
        log.append_log(' message\n127.0.0.1 "GET / HTTP/1.1" 200 -\n127.0.0.1 "PUT /file HTTP/1.1" 201 -\n')
        log.category.setCurrentIndex(log.category.findData('error'))
        self.assertEqual(log.log_text.toPlainText(), 'Error: fragmented message')
        log.category.setCurrentIndex(log.category.findData('access'))
        self.assertIn('GET /', log.log_text.toPlainText())
        self.assertNotIn('PUT /', log.log_text.toPlainText())
        log.category.setCurrentIndex(0)
        log.search.setText('file')
        path = os.path.join(self.temp_dir.name, 'logs.txt')
        with patch('src.gui.dialogs.QFileDialog.getSaveFileName', return_value=(path, '')):
            log.export_logs()
        with open(path, encoding='utf-8') as file: self.assertIn('PUT /file', file.read())
        log.clear_logs()
        self.assertEqual(log.log_text.toPlainText(), '')
        log.search.clear()

    def test_unimplemented_controls_are_disabled_and_translated(self):
        controller = self.controller
        for name in controller.unavailable_checks:
            field = getattr(controller.window, name)
            self.assertFalse(field.isEnabled())
            self.assertIn('(indisponível)', field.text())

    def test_switch_preserves_values_and_running_server(self):
        controller = self.controller
        window = controller.window
        self.assertEqual(controller.language.code, "pt")
        self.assertEqual(window.groupBox_files.title(), "Arquivos")
        window.line_username.setText("Username")
        window.line_password.setText("Password")
        window.line_root_folder.setText(self.temp_dir.name)
        window.combo_interface.setCurrentIndex(1)
        window.line_port.setText("0")
        controller._start_server()
        self.assertTrue(controller.server_manager.is_running)
        httpd = controller.server_manager.httpd
        controller.navigation.actions['language_en'].trigger()
        self.assertEqual(window.btn_start.text(), "STOP")
        self.assertEqual(window.lbl_status.text(), "RUNNING 🚀")
        self.assertEqual(window.groupBox_files.title(), "Files")
        self.assertFalse(window.line_port.isEnabled())
        self.assertTrue(controller.navigation.menus['Language'].isEnabled())
        controller.navigation.actions['language_pt'].trigger()
        self.assertEqual(window.btn_start.text(), "PARAR")
        self.assertEqual(window.lbl_status.text(), "EM EXECUÇÃO 🚀")
        self.assertEqual(controller.log_window.windowTitle(), "Registros do servidor")
        self.assertEqual(window.line_username.text(), "Username")
        self.assertEqual(window.line_password.text(), "Password")
        self.assertEqual(window.line_root_folder.text(), self.temp_dir.name)
        self.assertEqual(window.line_username.placeholderText(), "Usuário")
        self.assertIs(controller.server_manager.httpd, httpd)
        self.settings.sync()
        restored = QSettings(self.settings.fileName(), QSettings.IniFormat)
        self.assertEqual(restored.value("interface_language"), "pt")
        controller._stop_server()
        self.assertEqual(window.btn_start.text(), "INICIAR")

    def test_dialog_translation_preserves_configuration(self):
        language = self.controller.language
        language.code = "pt"
        config = {"origin": "https://example.com", "methods": "GET", "headers": "Authorization"}
        cors = CORSDialog(config, language=language)
        self.assertEqual(cors.windowTitle(), "Configurar CORS")
        self.assertEqual(cors.get_config(), config)
        self.assertEqual(cors.buttons.button(QDialogButtonBox.Cancel).text(), "Cancelar")
        redirections = [("/Path", "https://example.com/Code", 301)]
        dialog = RedirectionDialog(redirections, language=language)
        self.assertEqual(dialog.table.horizontalHeaderItem(0).text(), "Caminho")
        self.assertEqual(dialog.get_redirections(), redirections)

    def test_server_preferences_restore_values_and_reject_invalid_paths(self):
        controller = self.controller
        window = controller.window
        window.line_root_folder.setText(self.temp_dir.name)
        window.line_port.setText('19123')
        window.combo_interface.setCurrentIndex(1)
        controller.save_server_preferences()
        window.line_port.setText('8080')
        window.line_root_folder.setText(os.getcwd())
        window.combo_interface.blockSignals(True)
        window.combo_interface.setCurrentIndex(0)
        window.combo_interface.blockSignals(False)
        controller.restore_server_preferences()
        self.assertEqual(window.line_port.text(), '19123')
        self.assertEqual(window.line_root_folder.text(), self.temp_dir.name)
        self.assertTrue(window.combo_interface.currentText().startswith('127.0.0.1'))
        window.line_port.setText('not-a-port')
        window.line_root_folder.setText(os.path.join(self.temp_dir.name, 'missing'))
        controller.save_server_preferences()
        self.assertEqual(self.settings.value('server/port'), '19123')
        self.assertEqual(self.settings.value('server/root_folder'), self.temp_dir.name)
