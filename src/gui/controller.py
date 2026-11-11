import sys
import os
import re
import psutil
import socket
import ssl
import ipaddress
import codecs
import json
import errno
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QComboBox, QHBoxLayout, QVBoxLayout, QWidget, QPushButton, QMessageBox, QGroupBox
from PySide6.QtGui import QDesktopServices
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QIODevice, Qt, QTimer, QTime, QSettings, QUrl
from .i18n import InterfaceLanguage
from .navigation import MainNavigation
from .server_config import build_server_config, normalize_public_hostname, ServerConfigurationError
from .network_tools import QRCodeDialog
from ..core.shares import validate_shared_folders
from ..core.access import validate_users
from ..core.privilege import release_replaced_instance
from .dialogs import StreamIntercept, LogWindow, CORSDialog, RedirectionDialog, ResponseHeadersDialog, AboutDialog, ShareFolderDialog, ActiveSharesDialog, PrinterSharingDialog, get_app_icon
from ..core.server import ServerManager
from ..core.startup import StartupRegistration
from ..core.response_headers import validate_response_headers
from ..core.windows_share import get_share_script_path, execute_share_script, is_windows_10_or_11
from ..core.platform_utils import is_platform_supported, is_linux
from processhunter.core.config import ConfigManager
from processhunter.core.hunter import ProcessHunter
from processhunter.core.logger import setup_app_logger


class AppController:
    """
    Main controller for the ServerPy application.
    Orchestrates the GUI and the underlying HTTP server.
    """
    PERSISTED_CHECKS = ('chk_render_pages', 'chk_allow_mod', 'chk_intent', 'chk_auth', 'chk_whitelist', 'chk_tls', 'chk_verify_header', 'chk_cloudflare_tunnel', 'chk_rate_limit', 'chk_custom_charset', 'chk_custom_headers', 'groupBox_schedule')
    def __init__(self):
        self.open_systemram_on_start = '--open-systemram' in sys.argv[1:]
        qt_args = [arg for arg in sys.argv if arg != '--open-systemram']
        self.app = QApplication.instance() or QApplication(qt_args)
        self.app.setStyle("Fusion")
        self.apply_dark_theme()
        self.setup_app_icon()
        self.settings = QSettings("ServerPy", "HTTPManager")
        self.language = InterfaceLanguage(self.settings.value("interface_language", "en"))
        self.selected_certificate = None
        self.restoring_preferences = False
        self.certificate_check = None

        self.server_manager = ServerManager()
        self.processhunter_config = ConfigManager()
        self.processhunter_config.load()
        self.process_hunter = ProcessHunter()
        self.processhunter_logger, _ = setup_app_logger()
        self.cert_path = "server.pem"
        self.cors_config = {
            'origin': '*', 
            'methods': 'GET, POST, OPTIONS, PUT, DELETE', 
            'headers': 'Content-Type, Authorization'
        }
        self.redirections = []
        self.custom_headers = {}
        self.shared_folders = []
        self.folder_users = []
        self.folder_users_enabled = False
        
        # Load UI
        ui_path = os.path.join(os.path.dirname(__file__), "serverpy.ui")
        ui_file = QFile(ui_path)
        if not ui_file.open(QIODevice.ReadOnly):
            print(f"Cannot open serverpy.ui: {ui_file.errorString()}")
            sys.exit(-1)
            
        loader = QUiLoader()
        self.window = loader.load(ui_file)
        ui_file.close()

        if not self.window:
            print(loader.errorString())
            sys.exit(-1)

        if hasattr(self, 'app_icon') and not self.app_icon.isNull():
            self.window.setWindowIcon(self.app_icon)

        self.setup_server_feedback()
        self.setup_advanced_settings()
        self.windows_share_supported = is_windows_10_or_11()
        self.network_share_supported = is_platform_supported()
        self.navigation = MainNavigation(self)
        self.app.aboutToQuit.connect(self.stop_processhunter)
        self.app.aboutToQuit.connect(self.stop_systemram)
        if self.open_systemram_on_start and self.navigation.systemram:
            self.navigation.tabs.setCurrentIndex(self.navigation.TAB_TITLES.index('SystemRAM'))
            
        self.ui_translations = self.language.capture(self.window)

        self.log_window = LogWindow(self.window, self.language)
        self.setup_logging()
        self.bind_ui()
        self.load_interfaces()
        self.restore_server_preferences()
        self.headers_button.setEnabled(self.window.chk_custom_headers.isChecked())
        self.window.line_port.editingFinished.connect(self.save_server_preferences)
        self.window.line_root_folder.editingFinished.connect(self.save_server_preferences)
        self.window.combo_interface.currentIndexChanged.connect(self.save_server_preferences)
        self.app.aboutToQuit.connect(self.save_server_preferences)
        self.bind_preferences_and_validation()
        self.window.line_cloudflare_hostname.setEnabled(self.window.chk_cloudflare_tunnel.isChecked())
        self.setup_autostart()
        self.setup_share_network()

        # Fix default folder if Android path or invalid
        current_folder = self.window.line_root_folder.text().strip()
        if not current_folder or "/storage/emulated" in current_folder or not os.path.exists(current_folder):
            self.window.line_root_folder.setText(os.getcwd())

        self.window.label_ip_info.setOpenExternalLinks(True)
        self.update_url()
        self.refresh_language()

        # Scheduler timer
        self.schedule_timer = QTimer()
        self.schedule_timer.timeout.connect(self.check_schedule)
        self.schedule_timer.start(10000)

    def show_about(self):
        AboutDialog(self.window, self.language).exec()

    def stop_processhunter(self):
        panel = getattr(getattr(self, 'navigation', None), 'process_hunter', None)
        if panel:
            if panel.scanner_worker and panel.scanner_worker.isRunning():
                panel.scanner_worker.wait(1500)
            if panel.sentinel_worker.isRunning():
                panel.sentinel_worker.stop()
                panel.sentinel_worker.wait(2000)

    def stop_systemram(self):
        panel = getattr(getattr(self, 'navigation', None), 'systemram', None)
        if panel:
            for worker in (panel.worker, panel.action_worker):
                if worker and worker.isRunning():
                    worker.wait(15000)

    def show_qr_code(self, url=None, temporary=False):
        if not self.server_manager.is_running:
            return
        url = url or self.access_combo.currentData()
        if url:
            if temporary:
                QRCodeDialog(url, self.window, self.language, temporary=True).exec()
            else:
                QRCodeDialog(url, self.window, self.language).exec()

    def setup_advanced_settings(self):
        field = self.window.chk_custom_headers
        parent = field.parentWidget()
        parent.layout().removeWidget(field)
        container = parent.parentWidget()
        self.advanced_group = QGroupBox('Advanced', container)
        self.advanced_group.setObjectName('groupBox_advanced')
        layout = QVBoxLayout(self.advanced_group)
        help_text = QLabel('Custom HTTP headers control caching, browser security and response metadata.', self.advanced_group)
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        layout.addWidget(field)
        self.headers_button = QPushButton('Configure headers', self.advanced_group)
        self.headers_button.setEnabled(False)
        self.headers_button.clicked.connect(self.on_config_headers)
        field.toggled.connect(self.headers_button.setEnabled)
        layout.addWidget(self.headers_button)
        container.layout().insertWidget(container.layout().indexOf(parent) + 1, self.advanced_group)

    def on_config_headers(self):
        dialog = ResponseHeadersDialog(self.custom_headers, self.window, self.language)
        if dialog.exec():
            self.custom_headers = dialog.get_headers()
            self.save_server_preferences()

    def setup_server_feedback(self):
        self.field_errors = {}
        for name in ('line_port', 'line_root_folder', 'line_username', 'line_password', 'line_whitelist', 'line_cloudflare_hostname', 'line_rate_limit', 'line_custom_charset', 'lbl_cert_info'):
            field = getattr(self.window, name)
            parent = field.parentWidget()
            wrapper = QWidget(parent)
            if parent.layout():
                parent.layout().replaceWidget(field, wrapper)
            layout = QVBoxLayout(wrapper)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(3)
            layout.addWidget(field)
            error = QLabel(wrapper)
            error.setWordWrap(True)
            error.setStyleSheet('color: #ff9aa7; font-size: 11px;')
            error.hide()
            layout.addWidget(error)
            self.field_errors[name] = error
        self.start_error = QLabel(self.window)
        self.start_error.setWordWrap(True)
        self.start_error.setStyleSheet('color: #ff9aa7;')
        self.window.groupBox_general.layout().addWidget(self.start_error)
        self.start_error.hide()
        self.start_error_source = ''
        self.access_combo = QComboBox(self.window)
        self.access_combo.setObjectName('combo_access_url')
        self.copy_url_button = QPushButton('Copy URL', self.window)
        self.open_url_button = QPushButton('Open in browser', self.window)
        self.qr_button = QPushButton('QR Code', self.window)
        row = QHBoxLayout()
        row.addWidget(self.access_combo, 1)
        row.addWidget(self.copy_url_button)
        row.addWidget(self.open_url_button)
        row.addWidget(self.qr_button)
        self.window.groupBox_general.layout().addLayout(row)
        self.copy_url_button.clicked.connect(self.copy_access_url)
        self.open_url_button.clicked.connect(self.open_access_url)
        self.qr_button.clicked.connect(lambda: self.show_qr_code())
        self.access_combo.currentIndexChanged.connect(self.update_qr_state)

    def update_qr_state(self):
        self.qr_button.setEnabled(self.server_manager.is_running and bool(self.access_combo.currentData()))

    def bind_preferences_and_validation(self):
        for name in self.PERSISTED_CHECKS:
            getattr(self.window, name).toggled.connect(self.save_server_preferences)
            getattr(self.window, name).toggled.connect(self.validate_inputs)
        self.window.chk_cloudflare_tunnel.toggled.connect(self.window.line_cloudflare_hostname.setEnabled)
        for name in ('line_port', 'line_root_folder', 'line_username', 'line_password', 'line_whitelist', 'line_cloudflare_hostname', 'line_rate_limit', 'line_custom_charset'):
            field = getattr(self.window, name)
            field.textChanged.connect(self.validate_inputs)
            field.textChanged.connect(self.clear_start_error)
            field.editingFinished.connect(self.save_server_preferences)
        for name in ('time_start', 'time_stop'):
            getattr(self.window, name).timeChanged.connect(self.save_server_preferences)
        self.unavailable_checks = ('chk_sqlite', 'chk_exclude_battery', 'chk_allow_external')
        for name in self.unavailable_checks:
            field = getattr(self.window, name)
            field.setChecked(False)
            field.setEnabled(False)

    def setup_autostart(self):
        self.startup = StartupRegistration()
        self.autostart_error = False
        self.autostart_enabled = False
        try:
            self.autostart_enabled = self.startup.is_enabled()
        except OSError as error:
            self.autostart_error = True
            print(f'Unable to read automatic startup: {error}')
        self.window.chk_autostart.setChecked(self.autostart_enabled)
        self.window.chk_autostart.setEnabled(self.startup.supported and not self.autostart_error)
        self.window.chk_autostart.toggled.connect(self.change_autostart)

    def change_autostart(self, enabled):
        try:
            self.startup.set_enabled(enabled)
        except OSError as error:
            field = self.window.chk_autostart
            field.blockSignals(True)
            field.setChecked(self.autostart_enabled)
            field.blockSignals(False)
            print(f'Unable to change automatic startup: {error}')
            QMessageBox.warning(self.window, self.language.text('Automatic startup'), self.language.text('Unable to change automatic startup. See logs for details.'))
        else:
            self.autostart_enabled = enabled

    def show_field_error(self, name, source):
        label = self.field_errors[name]
        label.setText(self.language.text(source) if source else '')
        label.setVisible(bool(source))
        field = getattr(self.window, name)
        field.setStyleSheet('border: 1px solid #ff9aa7;' if source and name != 'lbl_cert_info' else '')
        field.setAccessibleDescription(label.text())

    def validate_inputs(self):
        errors = {}
        port = self.window.line_port.text().strip()
        if len(port) > 5 or not port.isascii() or not port.isdigit() or not 0 <= int(port) <= 65535:
            errors['line_port'] = 'Enter a port from 0 to 65535 (0 selects an available port).'
        folder = self.window.line_root_folder.text().strip()
        if not folder or not os.path.isdir(folder):
            errors['line_root_folder'] = 'Select an existing folder.'
        elif not os.access(folder, os.R_OK | os.X_OK):
            errors['line_root_folder'] = 'The selected folder cannot be accessed.'
        if self.window.chk_auth.isChecked():
            if not self.window.line_username.text(): errors['line_username'] = 'Enter a username.'
            if not self.window.line_password.text(): errors['line_password'] = 'Enter a password.'
        if self.window.chk_whitelist.isChecked():
            addresses = [ip.strip() for ip in self.window.line_whitelist.text().split(',') if ip.strip()]
            try:
                if not addresses: raise ValueError()
                for address in addresses: ipaddress.ip_address(address)
            except ValueError:
                errors['line_whitelist'] = 'Enter valid IP addresses separated by commas.'
        if self.window.chk_cloudflare_tunnel.isChecked() and not normalize_public_hostname(self.window.line_cloudflare_hostname.text()):
            errors['line_cloudflare_hostname'] = 'Enter a valid public hostname, such as files.example.com.'
        if self.window.chk_rate_limit.isChecked():
            rate = self.window.line_rate_limit.text().strip()
            if len(rate) > 9 or not rate.isascii() or not rate.isdigit() or int(rate) < 1:
                errors['line_rate_limit'] = 'Enter a positive request limit.'
        if self.window.chk_custom_charset.isChecked():
            try: codecs.lookup(self.window.line_custom_charset.text().strip())
            except LookupError: errors['line_custom_charset'] = 'Enter a supported character encoding.'
        if self.window.chk_tls.isChecked():
            if not os.path.isfile(self.cert_path):
                errors['lbl_cert_info'] = 'Select a PEM certificate containing its private key.'
            else:
                try:
                    stat = os.stat(self.cert_path)
                    fingerprint = (self.cert_path, stat.st_mtime_ns, stat.st_size)
                    if not self.certificate_check or self.certificate_check[0] != fingerprint:
                        try:
                            ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(self.cert_path, password=lambda: '')
                            self.certificate_check = (fingerprint, '')
                        except (OSError, ssl.SSLError):
                            self.certificate_check = (fingerprint, 'The PEM certificate or private key is invalid or encrypted.')
                    if self.certificate_check[1]: errors['lbl_cert_info'] = self.certificate_check[1]
                except OSError:
                    errors['lbl_cert_info'] = 'The certificate file cannot be read.'
        for name in self.field_errors:
            self.show_field_error(name, errors.get(name, ''))
        self.validation_errors = errors
        self.window.btn_start.setEnabled(self.server_manager.is_running or not errors)
        self.navigation.update_server_actions()
        return not errors

    def copy_access_url(self):
        if self.access_combo.currentData():
            self.app.clipboard().setText(self.access_combo.currentData())
            self.access_combo.setToolTip(self.language.text('URL copied.'))

    def clear_start_error(self):
        self.start_error_source = ''
        self.start_error.hide()

    def open_access_url(self):
        if self.server_manager.is_running and self.access_combo.currentData():
            QDesktopServices.openUrl(QUrl(self.access_combo.currentData()))

    def restore_server_preferences(self, profile=None):
        self.restoring_preferences = True
        folder = profile['root_folder'] if profile is not None else self.settings.value("server/root_folder", "")
        if isinstance(folder, str) and folder and os.path.isdir(folder):
            self.window.line_root_folder.setText(folder)
        port = profile['port'] if profile is not None else str(self.settings.value("server/port", "8080"))
        if len(port) <= 5 and port.isascii() and port.isdigit() and 0 <= int(port) <= 65535:
            self.window.line_port.setText(port)
        interface = profile['interface'] if profile is not None else self.settings.value("server/interface", "0.0.0.0")
        for index in range(self.window.combo_interface.count()):
            if self.window.combo_interface.itemText(index).split()[0] == interface:
                self.window.combo_interface.setCurrentIndex(index)
                break
        try:
            options = profile['options'] if profile is not None else json.loads(self.settings.value('server/options', '{}'))
        except (ValueError, TypeError):
            options = {}
        if not isinstance(options, dict): options = {}
        try:
            self.shared_folders = validate_shared_folders(options.get('shared_folders', []), check_paths=False)
        except ValueError:
            self.shared_folders = []
        self.navigation.shared_folders.reload()
        try:
            self.folder_users = validate_users(options.get('folder_users', []))
        except ValueError:
            self.folder_users = []
        self.folder_users_enabled = options.get('folder_users_enabled') is True
        self.navigation.access.retranslate()
        cert_path = options.get('certificate')
        if isinstance(cert_path, str) and cert_path:
            self.cert_path = cert_path
            self.selected_certificate = os.path.basename(cert_path)
        for name in self.PERSISTED_CHECKS:
            if isinstance(options.get(name), bool):
                getattr(self.window, name).setChecked(options[name])
        for name in ('line_whitelist', 'line_cloudflare_hostname', 'line_rate_limit', 'line_custom_charset'):
            if isinstance(options.get(name), str): getattr(self.window, name).setText(options[name])
        for name in ('time_start', 'time_stop'):
            time = QTime.fromString(options.get(name, ''), 'HH:mm:ss') if isinstance(options.get(name, ''), str) else QTime()
            if time.isValid(): getattr(self.window, name).setTime(time)
        cors = options.get('cors')
        headers = options.get('custom_headers', {})
        try:
            self.custom_headers = validate_response_headers(headers) if isinstance(headers, dict) else {}
        except ValueError:
            self.custom_headers = {}
        if isinstance(cors, dict) and all(isinstance(cors.get(key), str) for key in ('origin', 'methods', 'headers')):
            self.cors_config = cors
        redirections = options.get('redirections')
        if isinstance(redirections, list):
            self.redirections = [tuple(row) for row in redirections if isinstance(row, list) and len(row) == 3 and isinstance(row[0], str) and isinstance(row[1], str) and row[2] in (301, 302, 303, 307, 308)]
        self.restoring_preferences = False

    def save_server_preferences(self):
        if self.restoring_preferences: return
        folder = self.window.line_root_folder.text().strip()
        if os.path.isdir(folder):
            self.settings.setValue("server/root_folder", os.path.abspath(folder))
        port = self.window.line_port.text().strip()
        if len(port) <= 5 and port.isascii() and port.isdigit() and 0 <= int(port) <= 65535:
            self.settings.setValue("server/port", port)
        interface = self.window.combo_interface.currentText().split()
        if interface:
            self.settings.setValue("server/interface", interface[0])
        options = {name: getattr(self.window, name).isChecked() for name in self.PERSISTED_CHECKS}
        options.update({name: getattr(self.window, name).text() for name in ('line_whitelist', 'line_cloudflare_hostname', 'line_rate_limit', 'line_custom_charset')})
        options.update({name: getattr(self.window, name).time().toString('HH:mm:ss') for name in ('time_start', 'time_stop')})
        options.update({'certificate': os.path.abspath(self.cert_path), 'cors': self.cors_config, 'redirections': self.redirections, 'custom_headers': self.custom_headers, 'shared_folders': self.shared_folders,
                        'folder_users': self.folder_users, 'folder_users_enabled': self.folder_users_enabled})
        self.settings.setValue('server/options', json.dumps(options, ensure_ascii=False))

    def change_language(self, code):
        if code not in ('en', 'pt') or code == self.language.code:
            return
        self.language.code = code
        self.settings.setValue("interface_language", self.language.code)
        self.refresh_language()

    def refresh_language(self):
        self.language.apply(self.ui_translations)
        self.window.combo_interface.setItemText(0, self.language.text("0.0.0.0 (All Interfaces)"))
        self.refresh_server_status()
        if self.selected_certificate:
            self.window.lbl_cert_info.setText(self.language.text("Selected: {filename}", filename=self.selected_certificate))
        self.log_window.retranslate()
        if hasattr(self, 'startup'):
            tip = 'Open the manager when you sign in. Start the server using the Start button.'
            if not self.startup.supported:
                tip = 'Automatic startup is not supported on this system.'
            elif self.autostart_error:
                tip = 'Unable to read automatic startup. See logs for details.'
            self.window.chk_autostart.setToolTip(self.language.text(tip))
        for name in getattr(self, 'unavailable_checks', ()):
            field = getattr(self.window, name)
            field.setText(field.text() + ' ' + self.language.text('(unavailable)'))
            field.setToolTip(self.language.text('This option is not implemented yet.'))
        self.validate_inputs()
        if self.start_error_source:
            self.start_error.setText(self.language.text(self.start_error_source))
        self.update_url()
        self.navigation.retranslate()

    def refresh_server_status(self):
        running = self.server_manager.is_running
        self.window.btn_start.setText(self.language.text("STOP" if running else "START"))
        self.window.lbl_status.setText(self.language.text("RUNNING 🚀" if running else "not running zzz"))

    def apply_dark_theme(self):
        from PySide6.QtGui import QPalette, QColor
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, Qt.black)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        self.app.setPalette(palette)

    def setup_logging(self):
        self.stream_interceptor_out = StreamIntercept(sys.__stdout__)
        self.stream_interceptor_out.text_written.connect(self.log_window.append_log)
        self.stream_interceptor_err = StreamIntercept(sys.__stderr__)
        self.stream_interceptor_err.text_written.connect(self.log_window.append_log)
        sys.stdout = self.stream_interceptor_out
        sys.stderr = self.stream_interceptor_err

    def bind_ui(self):
        # Buttons
        self.window.btn_browse_folder.clicked.connect(self.browse_folder)
        self.window.btn_start.clicked.connect(self.toggle_server)
        self.window.btn_logs.clicked.connect(self.log_window.show)
        self.window.btn_install_cert.clicked.connect(self.install_cert)
        self.window.btn_config_cors.clicked.connect(self.on_config_cors)
        self.window.btn_edit_redirections.clicked.connect(self.on_edit_redirections)
        
        # Inputs & Checks
        self.window.combo_interface.currentTextChanged.connect(self.update_url)
        self.window.line_port.textChanged.connect(self.update_url)
        self.window.chk_tls.stateChanged.connect(self.on_tls_changed)
        self.window.chk_auth.stateChanged.connect(self.on_auth_changed)
        self.window.chk_whitelist.stateChanged.connect(self.on_whitelist_changed)
        self.window.chk_rate_limit.stateChanged.connect(self.on_rate_limit_changed)
        self.window.chk_custom_charset.stateChanged.connect(self.on_charset_changed)
        
        # Default states
        self.window.btn_install_cert.setEnabled(False)

    def load_interfaces(self):
        self.window.combo_interface.clear()
        self.window.combo_interface.addItem("0.0.0.0 (All Interfaces)")
        self.window.combo_interface.addItem("127.0.0.1 (Localhost)")
        try:
            addrs = psutil.net_if_addrs()
            for interface_name, interface_addresses in addrs.items():
                for addr in interface_addresses:
                    if addr.family == socket.AF_INET and addr.address != "127.0.0.1":
                        self.window.combo_interface.addItem(f"{addr.address} ({interface_name})")
        except Exception as e:
            print(f"Error loading network interfaces: {e}")

    def update_url(self):
        text = self.window.combo_interface.currentText()
        if not text: return
        interface = text.split()[0]
        port = self.window.line_port.text().strip()
        running = self.server_manager.is_running
        if running:
            interface, port = self.server_manager.httpd.server_address[:2]
        protocol = 'https' if self.window.chk_tls.isChecked() else 'http'
        hosts = [interface] if interface not in ('', '0.0.0.0') else ['127.0.0.1']
        if interface in ('', '0.0.0.0'):
            try:
                for name, addresses in psutil.net_if_addrs().items():
                    for address in addresses:
                        if address.family == socket.AF_INET and address.address not in hosts and not address.address.startswith('127.'):
                            hosts.append(address.address)
            except OSError:
                pass
        valid_port = len(str(port)) <= 5 and str(port).isascii() and str(port).isdigit() and 0 < int(port) <= 65535
        previous = self.access_combo.currentData()
        self.access_combo.clear()
        if valid_port:
            for host in hosts:
                url = f'{protocol}://{host}:{port}'
                self.access_combo.addItem(url, url)
            index = self.access_combo.findData(previous)
            if index >= 0: self.access_combo.setCurrentIndex(index)
        self.copy_url_button.setEnabled(valid_port)
        self.open_url_button.setEnabled(valid_port and running)
        url = self.access_combo.currentData()
        self.window.lbl_url.setText(url or self.language.text('Available after starting the server.'))
        if running and url:
            self.window.label_ip_info.setText(f"{self.language.text('Server URL:')} <a href='{url}' style='color: #78a7ff;'>{url}</a>")
        else:
            self.window.label_ip_info.setText(self.language.text('Choose an address below. Links become active when the server starts.'))
        self.navigation.update_server_actions()
        self.update_qr_state()

    def check_schedule(self):
        if not self.window.groupBox_schedule.isChecked():
            return
            
        start_time = self.window.time_start.time()
        stop_time = self.window.time_stop.time()
        current_time = QTime.currentTime()
        
        should_run = False
        if start_time < stop_time:
            should_run = start_time <= current_time <= stop_time
        else: # Over midnight
            should_run = current_time >= start_time or current_time <= stop_time
            
        if should_run and not self.server_manager.is_running:
            self.toggle_server()
        elif not should_run and self.server_manager.is_running:
            self.toggle_server()

    def on_auth_changed(self):
        self.window.widget_auth_credentials.setEnabled(self.window.chk_auth.isChecked())

    def on_whitelist_changed(self):
        self.window.widget_whitelist.setEnabled(self.window.chk_whitelist.isChecked())
        
    def on_rate_limit_changed(self):
        self.window.widget_rate_limit.setEnabled(self.window.chk_rate_limit.isChecked())

    def on_charset_changed(self):
        self.window.widget_custom_charset.setEnabled(self.window.chk_custom_charset.isChecked())

    def on_tls_changed(self):
        self.window.btn_install_cert.setEnabled(self.window.chk_tls.isChecked())
        self.update_url()

    def on_config_cors(self):
        dialog = CORSDialog(self.cors_config, self.window, self.language)
        if dialog.exec():
            self.cors_config = dialog.get_config()
            self.save_server_preferences()

    def on_edit_redirections(self):
        dialog = RedirectionDialog(self.redirections, self.window, self.language)
        if dialog.exec():
            self.redirections = dialog.get_redirections()
            self.save_server_preferences()

    def browse_folder(self):
        current = self.window.line_root_folder.text()
        dir_path = QFileDialog.getExistingDirectory(self.window, self.language.text("Select Directory"), current)
        if dir_path:
            self.window.line_root_folder.setText(dir_path)

    def install_cert(self):
        file_path, _ = QFileDialog.getOpenFileName(self.window, self.language.text("Select Certificate"), "", self.language.text("Certificates (*.pem *.crt *.cer);;All Files (*)"))
        if file_path:
            self.cert_path = file_path
            filename = os.path.basename(file_path)
            self.selected_certificate = filename
            self.window.lbl_cert_info.setText(self.language.text("Selected: {filename}", filename=filename))
            self.validate_inputs()
            self.save_server_preferences()

    def toggle_server(self):
        if not self.server_manager.is_running:
            self._start_server()
        else:
            self._stop_server()

    def _start_server(self):
        self.start_error.hide()
        if not self.validate_inputs():
            getattr(self.window, next(iter(self.validation_errors))).setFocus()
            return
        if self.folder_users_enabled and not self.folder_users:
            source = 'Add at least one folder user in Security, or disable individual folder permissions.'
            self.start_error.setText(self.language.text(source))
            self.start_error_source = source
            self.start_error.show()
            self.navigation.tabs.setCurrentIndex(self.navigation.TAB_TITLES.index('Security'))
            return
        self.save_server_preferences()
        # Extract UI values
        interface_text = self.window.combo_interface.currentText().split()[0]
        host = "" if interface_text == "0.0.0.0" else interface_text
        
        try:
            port = int(self.window.line_port.text())
        except ValueError:
            print(self.language.text("Error: Invalid port number."))
            return

        directory = self.window.line_root_folder.text().strip()
        if not directory or not os.path.isdir(directory):
            print(self.language.text("Error: Directory '{directory}' does not exist or is not a valid folder.", directory=directory))
            return
        
        try:
            config = build_server_config(self)
        except ServerConfigurationError as error:
            source = str(error)
            message = self.language.text(source)
            print(message)
            self.start_error.setText(message)
            self.start_error_source = source
            self.start_error.show()
            return

        # Start server
        success, msg = self.server_manager.start_server(host, port, directory, **config)
        print(msg)
        
        if success:
            self.refresh_server_status()
            self.window.lbl_status.setStyleSheet("color: #2ecc71; font-weight: bold;")
            self._set_ui_enabled(False)
            self.update_url()
        else:
            error = self.server_manager.last_error
            blocked_port = getattr(error, 'errno', None) in (errno.EADDRINUSE, errno.EACCES) or getattr(error, 'winerror', None) in (10048, 10013)
            source = 'Port is in use or unavailable. Choose another port.' if blocked_port else 'Unable to start the server. See logs for details.'
            self.start_error.setText(self.language.text(source))
            self.start_error_source = source
            self.start_error.show()

    def _stop_server(self):
        self.server_manager.stop_server()
        print(self.language.text("Server stopped."))
        self.refresh_server_status()
        self.window.lbl_status.setStyleSheet("color: white;")
        self._set_ui_enabled(True)
        self.update_url()

    def _set_ui_enabled(self, enabled):
        primary_widgets = [
            self.window.combo_interface, self.window.line_port, self.window.chk_tls,
            self.window.chk_auth, self.window.chk_render_pages, self.window.chk_allow_mod,
            self.window.chk_intent, self.window.chk_whitelist, self.window.chk_verify_header,
            self.window.chk_cloudflare_tunnel, self.window.line_cloudflare_hostname,
            self.window.chk_rate_limit, self.window.chk_custom_charset,
            self.window.btn_browse_folder, self.window.line_root_folder
        ]
        for w in primary_widgets:
            w.setEnabled(enabled)

        if enabled:
            # Reapply dependent widgets based on checkbox states
            self.on_auth_changed()
            self.on_whitelist_changed()
            self.on_rate_limit_changed()
            self.on_charset_changed()
            self.on_tls_changed()
            self.window.line_cloudflare_hostname.setEnabled(self.window.chk_cloudflare_tunnel.isChecked())
        else:
            self.window.widget_auth_credentials.setEnabled(False)
            self.window.widget_whitelist.setEnabled(False)
            self.window.widget_rate_limit.setEnabled(False)
            self.window.widget_custom_charset.setEnabled(False)
            self.window.btn_install_cert.setEnabled(False)

    def setup_app_icon(self):
        if sys.platform == 'win32':
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('krakentech.serverpy.httpmanager')
            except Exception:
                pass
        icon = get_app_icon()
        if not icon.isNull():
            self.app_icon = icon
            self.app.setWindowIcon(icon)
            if hasattr(self, 'window') and self.window:
                self.window.setWindowIcon(icon)
            if hasattr(self, 'log_window') and self.log_window:
                self.log_window.setWindowIcon(icon)

    def setup_share_network(self):
        btn_share = getattr(self.window, 'btn_share_network', None)
        btn_manage = getattr(self.window, 'btn_manage_shares', None)
        btn_printers = getattr(self.window, 'btn_share_printers', None)
        supported = self.network_share_supported
        for btn in (btn_share, btn_manage):
            if btn:
                btn.setVisible(supported)
                btn.setEnabled(supported)
        if btn_printers:
            btn_printers.setVisible(self.windows_share_supported)
            btn_printers.setEnabled(self.windows_share_supported)
        if btn_share and supported:
            btn_share.clicked.connect(self.on_share_folder_network)
        if btn_manage and supported:
            btn_manage.clicked.connect(self.on_manage_shares)
        if btn_printers and self.windows_share_supported:
            btn_printers.clicked.connect(self.on_share_printers)

    def on_share_folder_network(self):
        folder = self.window.line_root_folder.text().strip()
        if not folder or not os.path.isdir(folder):
            folder = os.getcwd()
        self.share_folder(folder)

    def share_folder(self, folder):
        """Open the same share configuration for a folder or an external volume."""
        if not os.path.isdir(folder):
            QMessageBox.warning(self.window, self.language.text('Share folder on network'), self.language.text('Select an existing folder.'))
            return
        dialog = ShareFolderDialog(folder, self.window, self.language)
        if dialog.exec():
            config = dialog.get_config()
            script_path = None
            if is_windows_10_or_11():
                script_path = get_share_script_path()
                if not script_path:
                    QMessageBox.warning(
                        self.window,
                        self.language.text('Share folder on network'),
                        self.language.text('The share-folder.ps1 script was not found.')
                    )
                    return
            print(f"[Network Share] Starting setup for '{config['folder']}' as '{config['name']}'...")
            success, msg = execute_share_script(
                folder=config['folder'],
                name=config['name'],
                user=config['user'],
                access=config['access'],
                without_password=config['without_password'],
                script_path=script_path
            )
            if success:
                print(f"[Network Share] {self.language.text(msg)}")
                self.show_share_addresses(config['name'] or os.path.basename(os.path.abspath(config['folder'])))
            else:
                print(f"[Network Share Error] {self.language.text(msg)}")
                if "canceled" not in msg.lower() and "cancelado" not in msg.lower():
                    QMessageBox.warning(
                        self.window,
                        self.language.text('Share folder on network'),
                        self.language.text('Unable to launch share script: {error}', error=msg)
                    )

    def show_share_addresses(self, share_name):
        share_name = re.sub(r'[^\w\- ]', '_', share_name.strip()) if share_name else ''
        lines = []
        try:
            for interface_name, addresses in psutil.net_if_addrs().items():
                for address in addresses:
                    if address.family == socket.AF_INET and not address.address.startswith('127.'):
                        host = address.address
                        path = f'{host}/{share_name}'
                        lines.append(f'{interface_name}: \\\\{host}\\{share_name}   |   smb://{path}')
        except OSError:
            pass
        if not lines:
            return
        text = 'Access the share from other devices using one of these addresses:\n\n' + '\n'.join(lines)
        print('[Network Share] ' + text.replace('\n\n', '\n'))
        QMessageBox.information(self.window, self.language.text('Share folder on network'), text)

    def on_manage_shares(self):
        dialog = ActiveSharesDialog(self.window, self.language)
        dialog.exec()

    def on_share_printers(self):
        dialog = PrinterSharingDialog(self.window, self.language)
        dialog.exec()

    def run(self):
        self.window.show()
        QTimer.singleShot(1000, release_replaced_instance)
        sys.exit(self.app.exec())
