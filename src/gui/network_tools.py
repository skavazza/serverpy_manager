"""Local QR code generation and asynchronous network diagnostics."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from threading import Event
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt
from PySide6.QtGui import QImage, QPainter, QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QPushButton, QFileDialog, QDialogButtonBox,
    QMessageBox, QSpinBox, QCheckBox, QComboBox, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from ..core.diagnostics import diagnose_endpoint
from ..core.ssh import (
    build_sftp_transfer, ssh_check_connection, ssh_open_terminal,
    list_sftp_directory, SFTPTransferCancelled, sftp_transfer_with_password,
    ssh_run_command, validate_ssh_target,
)
from .dialogs import get_app_icon


def qr_image(url):
    import qrcode
    code = qrcode.QRCode(border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(url)
    code.make(fit=True)
    matrix = code.get_matrix()
    scale = max(4, 320 // len(matrix))
    image = QImage(len(matrix) * scale, len(matrix) * scale, QImage.Format_RGB32)
    image.fill(QColor('white'))
    painter = QPainter(image)
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                painter.fillRect(x * scale, y * scale, scale, scale, QColor('black'))
    painter.end()
    return image


class QRCodeDialog(QDialog):
    def __init__(self, url, parent, language, temporary=False):
        super().__init__(parent)
        self.language = language
        self.url = url
        self.setWindowTitle(language.text('Access by QR Code'))
        self.setWindowIcon(get_app_icon())
        layout = QVBoxLayout(self)
        self.image = qr_image(url)
        preview = QLabel(self)
        preview.setPixmap(QPixmap.fromImage(self.image))
        preview.setAlignment(Qt.AlignCenter)
        layout.addWidget(preview)
        address = QLineEdit(url, self)
        address.setReadOnly(True)
        layout.addWidget(address)
        host = urlsplit(url).hostname
        note = 'This address works only on this computer. Select a LAN address to connect your phone.' if host in ('localhost', '127.0.0.1', '::1') else 'Connect your phone to the same network. Authentication is still required when enabled.'
        if temporary:
            note = language.text('This QR Code grants access only to the linked file. The link password is required when configured.') + '\n' + language.text(
                'This address works only on this computer. Select a LAN address to connect your phone.' if host in ('localhost', '127.0.0.1', '::1') else 'Connect your phone to the same network.')
        label = QLabel(language.text(note), self)
        label.setWordWrap(True)
        layout.addWidget(label)
        save = QPushButton(language.text('Save QR Code'), self)
        save.clicked.connect(self.save)
        layout.addWidget(save)
        close = QDialogButtonBox(QDialogButtonBox.Close, self)
        close.button(QDialogButtonBox.Close).setText(language.text('Close'))
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def save(self):
        path, _ = QFileDialog.getSaveFileName(self, self.language.text('Save QR Code'), 'serverpy-qr.png', 'PNG (*.png)')
        if path:
            if not path.lower().endswith('.png'):
                path += '.png'
            if not self.image.save(path, 'PNG'):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, self.windowTitle(), self.language.text('Unable to save QR Code.'))


class _Signals(QObject):
    finished = Signal(object)
    progress = Signal(int, int)


class _DiagnosticTask(QRunnable):
    def __init__(self, host, port, tls):
        super().__init__()
        self.arguments = host, port, tls
        self.signals = _Signals()

    def run(self):
        try:
            result = diagnose_endpoint(*self.arguments)
        except Exception as error:
            result = [('Diagnostics', 'Failed', str(error))]
        self.signals.finished.emit(result)


class _SSHTask(QRunnable):
    def __init__(self, operation, action):
        super().__init__()
        self.operation = operation
        self.action = action
        self.signals = _Signals()

    def run(self):
        operation = self.operation
        self.operation = None
        try:
            result = operation()
        except (FileNotFoundError, OSError, TimeoutError, ValueError) as error:
            result = False, str(error)
        self.signals.finished.emit((self.action, result))


class _SFTPTask(QRunnable):
    def __init__(
        self, arguments, batch, direction, temporary_path=None, destination=None,
        password_auth=None,
    ):
        super().__init__()
        self.arguments = arguments
        self.batch = batch
        self.direction = direction
        self.temporary_path = temporary_path
        self.destination = destination
        self.password_auth = password_auth
        self.cancelled = Event()
        self.signals = _Signals()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        process = None
        success = False
        message = 'SFTP transfer cancelled.'
        try:
            if self.password_auth:
                host, username, port, password, local_path, remote_path = self.password_auth
                sftp_transfer_with_password(
                    host, username, port, password, self.direction, local_path,
                    remote_path, self.cancelled, self.signals.progress.emit,
                )
                return_code, output = 0, ''
            else:
                process = subprocess.Popen(
                    self.arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True,
                )
                batch = self.batch
                while True:
                    if self.cancelled.is_set():
                        if process.poll() is None:
                            process.terminate()
                            try:
                                process.communicate(timeout=2)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.communicate()
                        output = ''
                        break
                    try:
                        output = process.communicate(input=batch, timeout=0.1)[0]
                        break
                    except subprocess.TimeoutExpired:
                        batch = None
                        continue
                return_code, output = process.returncode, output.strip()
            if not self.cancelled.is_set() and return_code == 0:
                if self.direction == 'download':
                    os.replace(self.temporary_path, self.destination)
                success = True
                message = 'SFTP transfer completed.'
            elif not self.cancelled.is_set():
                message = output or 'SFTP transfer failed.'
        except SFTPTransferCancelled:
            self.cancelled.set()
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            message = str(error)
        finally:
            if self.temporary_path:
                try:
                    Path(self.temporary_path).unlink(missing_ok=True)
                except OSError as error:
                    success = False
                    message = f'{message} Unable to remove the temporary download file: {error}'
            self.password_auth = None
        self.signals.finished.emit(('transfer', (success, message)))


class _SFTPListTask(QRunnable):
    def __init__(self, arguments):
        super().__init__()
        self.arguments = arguments
        self.signals = _Signals(QApplication.instance())

    def run(self):
        try:
            host, username, port, identity_file, auth_method, password, remote_path = self.arguments
            entries = list_sftp_directory(
                host, username, port, identity_file, remote_path,
                auth_method=auth_method, password=password,
            )
            result = True, entries
        except (FileNotFoundError, OSError, TimeoutError, ValueError) as error:
            result = False, str(error)
        self.arguments = None
        self.signals.finished.emit(result)
        self.signals.deleteLater()


class SFTPBrowserDialog(QDialog):
    def __init__(self, controller, target, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.target = target
        self.remote_path = '/'
        self.selected_path = None
        self.back_history = []
        self.forward_history = []
        self.setWindowTitle(controller.language.text('Browse remote files'))
        layout = QVBoxLayout(self)
        path_row = QHBoxLayout()
        self.back_button = QPushButton('Back', self)
        self.forward_button = QPushButton('Forward', self)
        self.path = QLineEdit(self.remote_path, self)
        self.go_button = QPushButton('Go', self)
        self.up_button = QPushButton('Parent folder', self)
        path_row.addWidget(self.back_button)
        path_row.addWidget(self.forward_button)
        path_row.addWidget(self.path)
        path_row.addWidget(self.go_button)
        path_row.addWidget(self.up_button)
        layout.addLayout(path_row)
        self.entries = QTreeWidget(self)
        self.entries.setHeaderLabels([
            controller.language.text('Name'),
            controller.language.text('Type'),
        ])
        self.entries.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.entries)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.use_button = QPushButton('Select file', self)
        self.use_button.setEnabled(False)
        self.close_button = QPushButton('Close', self)
        actions.addStretch()
        actions.addWidget(self.use_button)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self.back_button.clicked.connect(self.back_directory)
        self.forward_button.clicked.connect(self.forward_directory)
        self.go_button.clicked.connect(lambda: self.navigate_directory(self.path.text()))
        self.up_button.clicked.connect(self.parent_directory)
        self.entries.itemDoubleClicked.connect(self.open_entry)
        self.entries.itemSelectionChanged.connect(self.update_actions)
        self.use_button.clicked.connect(self.select_file)
        self.close_button.clicked.connect(self.reject)
        self.labels = controller.language.capture(self)
        controller.language.apply(self.labels)
        self.load_directory('/')

    def load_directory(self, remote_path):
        path = str(remote_path).strip() or '/'
        normalized_path = str(PurePosixPath(path))
        if not normalized_path.startswith('/'):
            normalized_path = '/' + normalized_path
        self.remote_path = normalized_path
        self.path.setText(self.remote_path)
        self.entries.clear()
        self.use_button.setEnabled(False)
        self.update_navigation_buttons(loading=True)
        self.status.setText(self.controller.language.text('Loading remote directory...'))
        self.task = _SFTPListTask((*self.target, self.remote_path))
        self.task.signals.finished.connect(self.listing_finished)
        QThreadPool.globalInstance().start(self.task)

    def listing_finished(self, result):
        ok, value = result
        self.update_navigation_buttons()
        if not ok:
            self.status.setText(self.controller.language.text('SFTP listing failed: {error}', error=value))
            return
        self.status.setText(self.controller.language.text('Remote directory loaded.'))
        for entry in value:
            item = QTreeWidgetItem([
                entry['name'],
                self.controller.language.text('Folder' if entry['is_dir'] else 'File'),
            ])
            item.setData(0, Qt.UserRole, entry)
            self.entries.addTopLevelItem(item)
        self.update_actions()

    def parent_directory(self):
        parent = str(PurePosixPath(self.remote_path).parent)
        self.navigate_directory(parent)

    def navigate_directory(self, remote_path):
        path = str(remote_path).strip() or '/'
        normalized_path = str(PurePosixPath(path))
        if not normalized_path.startswith('/'):
            normalized_path = '/' + normalized_path
        if normalized_path != self.remote_path:
            self.back_history.append(self.remote_path)
            self.forward_history.clear()
        self.load_directory(normalized_path)

    def back_directory(self):
        if not self.back_history:
            return
        self.forward_history.append(self.remote_path)
        self.load_directory(self.back_history.pop())

    def forward_directory(self):
        if not self.forward_history:
            return
        self.back_history.append(self.remote_path)
        self.load_directory(self.forward_history.pop())

    def update_navigation_buttons(self, loading=False):
        self.back_button.setEnabled(not loading and bool(self.back_history))
        self.forward_button.setEnabled(not loading and bool(self.forward_history))
        self.go_button.setEnabled(not loading)
        self.up_button.setEnabled(not loading and self.remote_path != '/')

    def open_entry(self, item, _column):
        entry = item.data(0, Qt.UserRole)
        if entry and entry['is_dir']:
            self.navigate_directory(str(PurePosixPath(self.remote_path) / entry['name']))
        else:
            self.select_file()

    def update_actions(self):
        item = self.entries.currentItem()
        entry = item.data(0, Qt.UserRole) if item else None
        self.use_button.setEnabled(bool(entry and not entry['is_dir']))

    def select_file(self):
        item = self.entries.currentItem()
        entry = item.data(0, Qt.UserRole) if item else None
        if not entry or entry['is_dir']:
            return
        self.selected_path = str(PurePosixPath(self.remote_path) / entry['name'])
        self.accept()


class SSHPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.saved_hosts = self._load_hosts()
        self.running = False
        self.status_source = 'SSH client is ready when OpenSSH is installed.'
        self.status_values = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        note = QLabel('Connect over SSH with a private key/agent or a password. Saved hosts and key paths are stored locally; passwords are kept only in memory and never saved.', self)
        note.setWordWrap(True)
        layout.addWidget(note)

        host_row = QHBoxLayout()
        self.host_combo = QComboBox(self)
        self.host_combo.addItem('Manual host', None)
        for item in self.saved_hosts:
            label = item.get('label') or f"{item.get('username', '') + '@' if item.get('username') else ''}{item.get('host', '')}:{item.get('port', 22)}"
            self.host_combo.addItem(label, item)
        self.host_combo.currentIndexChanged.connect(self.apply_saved_host)
        host_row.addWidget(self.host_combo)
        self.save_button = QPushButton('Save host', self)
        self.delete_button = QPushButton('Delete', self)
        host_row.addWidget(self.save_button)
        host_row.addWidget(self.delete_button)
        layout.addLayout(host_row)

        form = QFormLayout()
        self.auth_form = form
        self.host = QLineEdit('localhost', self)
        self.port = QSpinBox(self)
        self.port.setRange(1, 65535)
        self.port.setValue(22)
        self.username = QLineEdit('', self)
        self.auth_method = QComboBox(self)
        self.auth_method.addItem('Private key / SSH agent', 'key')
        self.auth_method.addItem('Username and password', 'password')
        self.password = QLineEdit(self)
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText('Password (not saved)')
        self.identity_file = QLineEdit('', self)
        self.identity_file.setReadOnly(True)
        self.key_row_widget = QWidget(self)
        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.addWidget(self.identity_file)
        self.identity_button = QPushButton('Select key...', self)
        self.clear_identity_button = QPushButton('Clear', self)
        key_row.addWidget(self.identity_button)
        key_row.addWidget(self.clear_identity_button)
        self.key_row_widget.setLayout(key_row)
        self.command = QLineEdit('uname -a', self)
        form.addRow('Host:', self.host)
        form.addRow('Port:', self.port)
        form.addRow('Username:', self.username)
        form.addRow('Authentication:', self.auth_method)
        form.addRow('Password:', self.password)
        form.addRow('Private key:', self.key_row_widget)
        form.addRow('Command:', self.command)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.check_button = QPushButton('Check SSH', self)
        self.open_button = QPushButton('Open terminal', self)
        self.run_button = QPushButton('Run command', self)
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.run_button)
        layout.addLayout(buttons)

        sftp_form = QFormLayout()
        self.remote_file = QLineEdit(self)
        self.remote_file.setPlaceholderText('/remote/path/file')
        remote_row = QHBoxLayout()
        remote_row.addWidget(self.remote_file)
        self.browse_remote_button = QPushButton('Browse...', self)
        remote_row.addWidget(self.browse_remote_button)
        sftp_form.addRow('Remote file:', remote_row)
        layout.addLayout(sftp_form)
        sftp_row = QHBoxLayout()
        self.upload_button = QPushButton('Upload file...', self)
        self.download_button = QPushButton('Download file...', self)
        self.cancel_transfer_button = QPushButton('Cancel transfer', self)
        self.cancel_transfer_button.setEnabled(False)
        sftp_row.addWidget(self.upload_button)
        sftp_row.addWidget(self.download_button)
        sftp_row.addWidget(self.cancel_transfer_button)
        layout.addLayout(sftp_row)
        self.transfer_progress = QProgressBar(self)
        self.transfer_progress.setRange(0, 0)
        self.transfer_progress.setTextVisible(False)
        self.transfer_progress.hide()
        layout.addWidget(self.transfer_progress)

        output_row = QHBoxLayout()
        output_row.addWidget(QLabel('Command output:', self))
        output_row.addStretch()
        self.copy_output_button = QPushButton('Copy output', self)
        self.clear_output_button = QPushButton('Clear output', self)
        output_row.addWidget(self.copy_output_button)
        output_row.addWidget(self.clear_output_button)
        layout.addLayout(output_row)
        self.output = QPlainTextEdit(self)
        self.output.setReadOnly(True)
        self.output.setPlaceholderText('Command results will appear here.')
        self.output.setMinimumHeight(120)
        layout.addWidget(self.output)

        self.status = QLabel(self.status_source, self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.labels = controller.language.capture(self)
        self.retranslate()
        self.auth_method.setItemText(0, controller.language.text('Private key / SSH agent'))
        self.auth_method.setItemText(1, controller.language.text('Username and password'))
        self.auth_method.currentIndexChanged.connect(self.update_auth_fields)
        self.update_auth_fields()
        self.check_button.clicked.connect(self.check_connection)
        self.open_button.clicked.connect(self.open_terminal)
        self.run_button.clicked.connect(self.run_command)
        self.save_button.clicked.connect(self.save_host)
        self.delete_button.clicked.connect(self.delete_host)
        self.identity_button.clicked.connect(self.select_identity_file)
        self.clear_identity_button.clicked.connect(self.identity_file.clear)
        self.upload_button.clicked.connect(self.upload_file)
        self.download_button.clicked.connect(self.download_file)
        self.cancel_transfer_button.clicked.connect(self.cancel_transfer)
        self.browse_remote_button.clicked.connect(self.browse_remote_file)
        self.copy_output_button.clicked.connect(self.copy_output)
        self.clear_output_button.clicked.connect(self.clear_output)
        self.output.textChanged.connect(self._update_output_actions)
        self._update_output_actions()

    def _load_hosts(self):
        settings = getattr(self.controller, 'settings', None)
        if settings is None:
            return []
        raw = settings.value('ssh_hosts', [])
        if not isinstance(raw, list):
            return []
        hosts = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            host = str(item.get('host', '')).strip()
            if not host:
                continue
            hosts.append({
                'host': host,
                'port': int(item.get('port', 22) or 22),
                'username': str(item.get('username', '')).strip(),
                'identity_file': str(item.get('identity_file', '')).strip(),
                'auth_method': str(item.get('auth_method', 'key')),
                'label': str(item.get('label', '')).strip() or f"{host}:{item.get('port', 22)}",
            })
        return hosts

    def _save_hosts(self):
        settings = getattr(self.controller, 'settings', None)
        if settings is not None:
            settings.setValue('ssh_hosts', self.saved_hosts)

    def _apply_target(self, host, port, username, identity_file='', auth_method='key'):
        self.host.setText(host)
        self.port.setValue(int(port))
        self.username.setText(username)
        self.identity_file.setText(identity_file)
        self.password.clear()
        index = self.auth_method.findData(auth_method)
        self.auth_method.setCurrentIndex(index if index >= 0 else 0)

    def apply_saved_host(self, index):
        data = self.host_combo.itemData(index)
        if not data:
            return
        self._apply_target(
            data.get('host', ''), data.get('port', 22), data.get('username', ''),
            data.get('identity_file', ''), data.get('auth_method', 'key'),
        )

    def update_auth_fields(self, _index=None):
        password_mode = self.auth_method.currentData() == 'password'
        self.password.setVisible(password_mode)
        password_label = self.auth_form.labelForField(self.password)
        if password_label:
            password_label.setVisible(password_mode)
        self.key_row_widget.setVisible(not password_mode)
        key_label = self.auth_form.labelForField(self.key_row_widget)
        if key_label:
            key_label.setVisible(not password_mode)
        if not password_mode:
            self.password.clear()

    def _authentication(self, require_password=True):
        auth_method = self.auth_method.currentData()
        if auth_method == 'password':
            password = self.password.text()
            if not self.username.text().strip():
                raise ValueError('Enter a username to use password authentication.')
            if require_password and not password:
                raise ValueError('Enter the SSH password.')
            return auth_method, None, password
        return auth_method, self.identity_file.text().strip() or None, None

    def select_identity_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.controller.language.text('Select SSH private key'),
            self.identity_file.text(), self.controller.language.text('All Files (*)'),
        )
        if path:
            self.identity_file.setText(path)

    def save_host(self):
        try:
            host, username, port = self._target()
        except ValueError as error:
            self._set_status(str(error))
            return
        label = f"{username + '@' if username else ''}{host}:{port}"
        identity_file = self.identity_file.text().strip()
        data = {
            'host': host, 'port': port, 'username': username,
            'identity_file': identity_file,
            'auth_method': self.auth_method.currentData(), 'label': label,
        }
        existing = next((index for index, item in enumerate(self.saved_hosts) if item.get('host') == host and item.get('port') == port and item.get('username') == username), None)
        if existing is not None:
            self.saved_hosts[existing] = data
        else:
            self.saved_hosts.append(data)
        self._save_hosts()
        self.host_combo.blockSignals(True)
        self.host_combo.clear()
        self.host_combo.addItem('Manual host', None)
        for item in self.saved_hosts:
            self.host_combo.addItem(item.get('label') or f"{item.get('username','') + '@' if item.get('username') else ''}{item.get('host')}:{item.get('port', 22)}", item)
        self.host_combo.blockSignals(False)
        self._set_status('Saved SSH host: {label}', label=label)

    def delete_host(self):
        data = self.host_combo.itemData(self.host_combo.currentIndex())
        if not data:
            self._set_status('Select a saved host to remove it.')
            return
        self.saved_hosts = [item for item in self.saved_hosts if not (item.get('host') == data.get('host') and item.get('port') == data.get('port') and item.get('username') == data.get('username'))]
        self._save_hosts()
        self.host_combo.blockSignals(True)
        self.host_combo.clear()
        self.host_combo.addItem('Manual host', None)
        for item in self.saved_hosts:
            self.host_combo.addItem(item.get('label') or f"{item.get('username','') + '@' if item.get('username') else ''}{item.get('host')}:{item.get('port', 22)}", item)
        self.host_combo.blockSignals(False)
        label = data.get('label') or data.get('host')
        self._set_status('Removed saved SSH host: {label}', label=label)

    def _target(self):
        username = self.username.text().strip()
        host = self.host.text().strip()
        if not host:
            raise ValueError('Enter a valid host name or IP address.')
        if username:
            validate_ssh_target(f'{username}@{host}', None, self.port.value())
        else:
            validate_ssh_target(host, None, self.port.value())
        return host, username, self.port.value()

    def _set_status(self, source, **values):
        self.status_source = source
        self.status_values = values
        self.retranslate()

    def _set_running(self, running):
        self.running = running
        for widget in (
            self.host_combo, self.save_button, self.delete_button, self.host,
            self.port, self.username, self.auth_method, self.password,
            self.identity_file, self.identity_button,
            self.clear_identity_button, self.command, self.check_button,
            self.open_button, self.run_button, self.remote_file,
            self.upload_button, self.download_button, self.browse_remote_button,
        ):
            widget.setEnabled(not running)

    def _update_output_actions(self):
        has_output = bool(self.output.toPlainText())
        self.copy_output_button.setEnabled(has_output)
        self.clear_output_button.setEnabled(has_output)

    def copy_output(self):
        QApplication.clipboard().setText(self.output.toPlainText())

    def clear_output(self):
        self.output.clear()

    def upload_file(self):
        if self.running:
            return
        local_path, _ = QFileDialog.getOpenFileName(
            self, self.controller.language.text('Select file to upload'),
        )
        if not local_path:
            return
        remote_path = self.remote_file.text().strip() or Path(local_path).name
        try:
            host, username, port = self._target()
            auth_method, identity_file, password = self._authentication()
            if auth_method == 'password':
                if not Path(local_path).is_file():
                    raise FileNotFoundError('Select an existing local file to upload.')
                self._validate_remote_path(remote_path)
                arguments, batch = None, None
            else:
                arguments, batch = build_sftp_transfer(
                    host, username, port, identity_file,
                    'upload', local_path, remote_path,
                )
        except (FileNotFoundError, ValueError) as error:
            self._set_status(str(error))
            return
        question = self.controller.language.text(
            'Upload to {path}? The remote file may be replaced.', path=remote_path,
        )
        if QMessageBox.question(
            self, self.controller.language.text('SFTP transfer'), question,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self.remote_file.setText(remote_path)
        password_auth = (
            host, username, port, password, local_path, remote_path,
        ) if password is not None else None
        self._start_sftp_task(arguments, batch, 'upload', password_auth=password_auth)

    def download_file(self):
        if self.running:
            return
        remote_path = self.remote_file.text().strip()
        if not remote_path:
            self._set_status('Enter a remote file path.')
            return
        default_name = PurePosixPath(remote_path).name
        local_path, _ = QFileDialog.getSaveFileName(
            self, self.controller.language.text('Save downloaded file'), default_name,
            options=QFileDialog.DontConfirmOverwrite,
        )
        if not local_path:
            return
        destination = Path(local_path)
        if destination.exists() and QMessageBox.question(
            self, self.controller.language.text('SFTP transfer'),
            self.controller.language.text('Replace the existing local file?'),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        temporary_path = None
        try:
            descriptor, temporary_path = tempfile.mkstemp(
                prefix=f'.{destination.name}.', suffix='.part',
                dir=str(destination.parent),
            )
            os.close(descriptor)
            host, username, port = self._target()
            auth_method, identity_file, password = self._authentication()
            if auth_method == 'password':
                self._validate_remote_path(remote_path)
                arguments, batch = None, None
            else:
                arguments, batch = build_sftp_transfer(
                    host, username, port, identity_file,
                    'download', temporary_path, remote_path,
                )
        except (FileNotFoundError, OSError, ValueError) as error:
            if temporary_path:
                Path(temporary_path).unlink(missing_ok=True)
            self._set_status(str(error))
            return
        self._start_sftp_task(
            arguments, batch, 'download', temporary_path, str(destination),
            password_auth=(host, username, port, password, temporary_path, remote_path)
            if password is not None else None,
        )

    @staticmethod
    def _validate_remote_path(remote_path):
        if not remote_path or any(character in remote_path for character in ('\0', '\n', '\r')):
            raise ValueError('Enter a valid SFTP file path without line breaks.')

    def _start_sftp_task(
        self, arguments, batch, direction, temporary_path=None, destination=None,
        password_auth=None,
    ):
        self._set_running(True)
        self.cancel_transfer_button.setEnabled(True)
        self.transfer_progress.show()
        self._set_status('SFTP transfer in progress...')
        self.task = _SFTPTask(
            arguments, batch, direction, temporary_path, destination, password_auth,
        )
        self.task.signals.finished.connect(self._operation_finished)
        self.task.signals.progress.connect(self._update_transfer_progress)
        QThreadPool.globalInstance().start(self.task)

    def _update_transfer_progress(self, transferred, total):
        if total > 0:
            self.transfer_progress.setRange(0, total)
            self.transfer_progress.setValue(min(transferred, total))

    def cancel_transfer(self):
        if self.running and isinstance(self.task, _SFTPTask):
            self.task.cancel()
            self.cancel_transfer_button.setEnabled(False)
            self._set_status('Cancelling SFTP transfer...')

    def browse_remote_file(self):
        if self.running:
            return
        try:
            host, username, port = self._target()
            auth_method, identity_file, password = self._authentication()
        except ValueError as error:
            self._set_status(str(error))
            return
        dialog = SFTPBrowserDialog(
            self.controller,
            (
                host, username, port, identity_file, auth_method, password,
            ),
            self,
        )
        try:
            if dialog.exec() == QDialog.Accepted and dialog.selected_path:
                self.remote_file.setText(dialog.selected_path)
        finally:
            dialog.target = (*dialog.target[:4], dialog.target[4], None)
            self.password.clear()

    def _start_task(self, action, operation):
        if action == 'command':
            self.clear_output()
        self._set_running(True)
        self._set_status('Checking SSH...' if action == 'check' else 'Running remote command...')
        self.task = _SSHTask(operation, action)
        self.task.signals.finished.connect(self._operation_finished)
        QThreadPool.globalInstance().start(self.task)

    def _operation_finished(self, result):
        action, (ok, message) = result
        self._set_running(False)
        self.password.clear()
        if action == 'transfer':
            self.cancel_transfer_button.setEnabled(False)
            self.transfer_progress.hide()
            if ok:
                self._set_status('SFTP transfer completed.')
            elif message == 'SFTP transfer cancelled.':
                self._set_status('SFTP transfer cancelled.')
            else:
                self.output.setPlainText(message)
                self._set_status('SFTP transfer failed.')
        elif action == 'check':
            if ok:
                self._set_status('SSH connection is available.')
            else:
                self._set_status('SSH check failed: {message}', message=message)
        elif ok:
            self.output.setPlainText(message)
            self._set_status('Remote command completed.')
        else:
            self.output.setPlainText(message)
            self._set_status('Remote command failed.')

    def check_connection(self):
        if self.running:
            return
        try:
            host, username, port = self._target()
        except ValueError as error:
            self._set_status(str(error))
            return
        try:
            auth_method, identity_file, password = self._authentication()
        except ValueError as error:
            self._set_status(str(error))
            return
        self._start_task('check', lambda: ssh_check_connection(
            host, username, port, identity_file=identity_file,
            auth_method=auth_method, password=password,
        ))

    def open_terminal(self):
        try:
            host, username, port = self._target()
            auth_method, identity_file, _password = self._authentication(require_password=False)
            process = ssh_open_terminal(
                host, username, port, identity_file=identity_file,
                auth_method=auth_method,
            )
            if process and process.poll() is None:
                self._set_status('Opened SSH terminal to {host}.', host=host)
            else:
                self._set_status('Unable to open a terminal for this SSH target.')
        except (FileNotFoundError, OSError, ValueError) as error:
            self._set_status(str(error))
        self.password.clear()

    def run_command(self):
        if self.running:
            return
        command = self.command.text().strip()
        if not command:
            self._set_status('Enter a command to run on the remote host.')
            return
        try:
            host, username, port = self._target()
        except ValueError as error:
            self._set_status(str(error))
            return
        try:
            auth_method, identity_file, password = self._authentication()
        except ValueError as error:
            self._set_status(str(error))
            return
        self._start_task('command', lambda: ssh_run_command(
            host, username, port, command, identity_file=identity_file,
            auth_method=auth_method, password=password,
        ))

    def retranslate(self):
        language = self.controller.language
        language.apply(self.labels)
        self.host_combo.setItemText(0, language.text('Manual host'))
        self.remote_file.setPlaceholderText(language.text('Remote file path'))
        self.password.setPlaceholderText(language.text('Password (not saved)'))
        self.auth_method.setItemText(0, language.text('Private key / SSH agent'))
        self.auth_method.setItemText(1, language.text('Username and password'))
        self.output.setPlaceholderText(language.text('Command results will appear here.'))
        self.status.setText(language.text(self.status_source, **self.status_values))


class NetworkPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.rows = []
        self.running = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel('Test a hostname or IP address and a single port. For Cloudflare Tunnel, test the local origin over HTTP if it has no TLS, and the public hostname over HTTPS. Results describe access from this computer; they do not prove access from other devices or identify firewall rules.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.host = QLineEdit('localhost', self)
        self.port = QSpinBox(self)
        self.port.setRange(1, 65535)
        self.port.setValue(8080)
        form.addRow('Host or IP:', self.host)
        form.addRow('Port:', self.port)
        self.tls = QCheckBox('Use HTTPS', self)
        form.addRow(self.tls)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.server_button = QPushButton('Use server address', self)
        self.phone_qr_button = QPushButton('Show phone QR Code', self)
        self.run_button = QPushButton('Run diagnostics', self)
        row.addWidget(self.server_button)
        row.addWidget(self.phone_qr_button)
        row.addWidget(self.run_button)
        layout.addLayout(row)
        self.table = QTableWidget(0, 3, self)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.status_source = ''
        self.server_button.clicked.connect(self.use_server)
        self.phone_qr_button.clicked.connect(self.show_phone_qr)
        self.run_button.clicked.connect(self.run_checks)
        self.controller.access_combo.currentIndexChanged.connect(self.update_qr_action)
        self.labels = controller.language.capture(self)
        self.retranslate()
        self.update_qr_action()

    def update_qr_action(self, _index=None):
        self.phone_qr_button.setEnabled(
            self.controller.server_manager.is_running
            and bool(self.controller.access_combo.currentData())
        )

    def show_phone_qr(self):
        url = self.controller.access_combo.currentData()
        if url and self.controller.server_manager.is_running:
            self.controller.show_qr_code(url)

    def use_server(self):
        url = self.controller.access_combo.currentData()
        if url:
            parsed = urlsplit(url)
            self.host.setText(parsed.hostname or 'localhost')
            self.port.setValue(parsed.port or (443 if parsed.scheme == 'https' else 80))
            self.tls.setChecked(parsed.scheme == 'https')

    def run_checks(self):
        if self.running:
            return
        host = self.host.text().strip()
        if not host or len(host) > 253 or any(c.isspace() or c in '/\\@?#' for c in host):
            self.status_source = 'Enter a hostname or IP address without a URL or port.'
            self.retranslate()
            return
        self.running = True
        self.rows = []
        self.status_source = 'Checking network...'
        self.retranslate()
        for widget in (
            self.host, self.port, self.tls, self.server_button,
            self.phone_qr_button, self.run_button,
        ):
            widget.setEnabled(False)
        self.task = _DiagnosticTask(host, self.port.value(), self.tls.isChecked())
        self.task.signals.finished.connect(self.finished)
        QThreadPool.globalInstance().start(self.task)

    def finished(self, rows):
        self.rows = rows
        self.running = False
        self.status_source = 'Diagnostics complete. An HTTP 401 response means the server requires authentication.'
        for widget in (
            self.host, self.port, self.tls, self.server_button,
            self.phone_qr_button, self.run_button,
        ):
            widget.setEnabled(True)
        self.update_qr_action()
        self.retranslate()

    def retranslate(self):
        language = self.controller.language
        language.apply(self.labels)
        self.table.setHorizontalHeaderLabels([language.text(s) for s in ('Check', 'Result', 'Details')])
        self.table.setRowCount(len(self.rows))
        for row, values in enumerate(self.rows):
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(language.text(value)))
        self.status.setText(language.text(self.status_source))
