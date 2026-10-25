"""VPN setup, WireGuard controls, and explicit HTTPS admission."""

import json
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QDialog, QDialogButtonBox, QInputDialog, QMessageBox,
    QFileDialog, QPlainTextEdit, QApplication, QGroupBox, QTabWidget,
)

from ..core.vpn import validate_network, wireguard_diagnostics
from ..core.wireguard_install import (
    install_wireguard as install_wireguard_package,
    wireguard_install_supported,
)
from ..core.privilege import elevation_available, relaunch_elevated
from ..core.vpn_registry import VPNRegistry
from ..core.vpn_enrollment import RemoteInvite, request_remote_admission
from ..core.vpn_admission_server import AdmissionServer
from ..core.vpn_backend import identity_store, tunnel_backend, vpn_data_directory, vpn_platform, WireGuardError
from ..core.vpn_service import ClientConnection


class _Signals(QObject):
    finished = Signal(object, str)


class _Task(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = _Signals()

    def run(self):
        try:
            result = self.operation()
        except WireGuardError as error:
            self.signals.finished.emit(None, str(error))
        except Exception:
            # Never show raw exceptions that could contain local secrets.
            self.signals.finished.emit(None, 'VPN operation failed. Check local data and permissions.')
        else:
            self.signals.finished.emit(result, '')
        finally:
            self.operation = None  # Release closures containing invite tokens.


class VPNPanel(QWidget):
    def __init__(self, controller, parent=None, *, directory=None):
        super().__init__(parent)
        self.controller = controller
        self.directory = Path(directory) if directory is not None else None
        self.registry = None
        self.busy = False
        self.loaded = False
        self.task = None
        self.message_source = ''
        self.wireguard_install_prompted = False
        self.listener = None
        self.closing = False
        self.wireguard = None
        self.tunnel_name = None
        self.tunnel_role = None
        self.tunnel_status = None
        self.server_udp_port = 51820
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        layout = QVBoxLayout(self)
        self.guide = QLabel(self)
        self.guide.setWordWrap(True)
        self.guide.setTextFormat(Qt.PlainText)
        layout.addWidget(self.guide)
        self.network_group = QGroupBox(self)
        network_layout = QVBoxLayout(self.network_group)
        self.note = QLabel(self.network_group)
        self.note.setWordWrap(True)
        network_layout.addWidget(self.note)
        self.diagnostic = QLabel(self.network_group)
        self.diagnostic.setWordWrap(True)
        network_layout.addWidget(self.diagnostic)
        self.install_wireguard_button = QPushButton(self)
        self.install_wireguard_button.clicked.connect(
            lambda checked=False: self.install_wireguard()
        )
        network_layout.addWidget(self.install_wireguard_button)
        self.elevate_button = QPushButton(self)
        self.elevate_button.clicked.connect(lambda checked=False: self.request_elevation())
        network_layout.addWidget(self.elevate_button)
        self.tunnel_label = QLabel(self.network_group)
        self.tunnel_label.setWordWrap(True)
        network_layout.addWidget(self.tunnel_label)
        layout.addWidget(self.network_group)

        self.mode_tabs = QTabWidget(self)
        layout.addWidget(self.mode_tabs, 1)
        self.create_tab = QWidget(self.mode_tabs)
        create_layout = QVBoxLayout(self.create_tab)
        self.connect_tab = QWidget(self.mode_tabs)
        connect_layout = QVBoxLayout(self.connect_tab)

        self.create_network_group = QGroupBox(self.create_tab)
        create_network_layout = QVBoxLayout(self.create_network_group)
        form = QFormLayout()
        self.cidr = QLineEdit('10.77.0.0/24', self)
        self.cidr.setMaxLength(32)
        self.cidr_label = QLabel(self)
        form.addRow(self.cidr_label, self.cidr)
        create_network_layout.addLayout(form)
        row = QHBoxLayout()
        self.buttons = {}
        for source, callback in (
            ('Prepare local VPN network', self.prepare),
            ('Refresh VPN status', self.refresh),
        ):
            button = QPushButton(self)
            button.clicked.connect(callback)
            row.addWidget(button)
            self.buttons[source] = button
        create_network_layout.addLayout(row)
        create_layout.addWidget(self.create_network_group)

        self.enrollment_group = QGroupBox(self.create_tab)
        enrollment_layout = QVBoxLayout(self.enrollment_group)
        self.enrollment_help = QLabel(self.enrollment_group)
        self.enrollment_help.setWordWrap(True)
        enrollment_layout.addWidget(self.enrollment_help)
        row = QHBoxLayout()
        for source, callback in (
            ('Start HTTPS enrollment', self.start_enrollment),
            ('Stop HTTPS enrollment', self.stop_enrollment),
            ('Generate remote invitation', self.remote_invite),
            ('Generate local invitation', self.invite),
        ):
            button = QPushButton(self)
            button.clicked.connect(callback)
            row.addWidget(button)
            self.buttons[source] = button
        enrollment_layout.addLayout(row)
        create_layout.addWidget(self.enrollment_group)

        self.tunnel_group = QGroupBox(self.create_tab)
        tunnel_layout = QVBoxLayout(self.tunnel_group)
        self.tunnel_help = QLabel(self.tunnel_group)
        self.tunnel_help.setWordWrap(True)
        tunnel_layout.addWidget(self.tunnel_help)
        row = QHBoxLayout()
        for source, callback in (
            ('Start WireGuard server', self.start_wireguard_server),
            ('Export client connection', self.export_connection),
        ):
            button = QPushButton(self)
            button.clicked.connect(callback)
            row.addWidget(button)
            self.buttons[source] = button
        tunnel_layout.addLayout(row)
        create_layout.addWidget(self.tunnel_group)

        self.devices_group = QGroupBox(self.create_tab)
        devices_layout = QVBoxLayout(self.devices_group)
        self.table = QTableWidget(0, 3, self.devices_group)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.update_actions)
        devices_layout.addWidget(self.table)
        row = QHBoxLayout()
        for source, state in (
            ('Approve device locally', 'approve'),
            ('Reject device locally', 'reject'),
            ('Revoke local authorization', 'revoke'),
        ):
            button = QPushButton(self.devices_group)
            button.clicked.connect(lambda checked=False, state=state: self.change_device(state))
            row.addWidget(button)
            self.buttons[source] = button
        devices_layout.addLayout(row)
        create_layout.addWidget(self.devices_group, 1)
        self.mode_tabs.addTab(self.create_tab, '')

        self.client_enrollment_group = QGroupBox(self.connect_tab)
        client_enrollment_layout = QVBoxLayout(self.client_enrollment_group)
        self.client_enrollment_help = QLabel(self.client_enrollment_group)
        self.client_enrollment_help.setWordWrap(True)
        client_enrollment_layout.addWidget(self.client_enrollment_help)
        self.review_button = QPushButton(self.client_enrollment_group)
        self.review_button.clicked.connect(self.review_invite)
        client_enrollment_layout.addWidget(self.review_button)
        self.buttons['Send enrollment request'] = QPushButton(self.client_enrollment_group)
        self.buttons['Send enrollment request'].clicked.connect(self.send_request)
        client_enrollment_layout.addWidget(self.buttons['Send enrollment request'])
        connect_layout.addWidget(self.client_enrollment_group)

        self.client_tunnel_group = QGroupBox(self.connect_tab)
        client_tunnel_layout = QVBoxLayout(self.client_tunnel_group)
        self.client_tunnel_help = QLabel(self.client_tunnel_group)
        self.client_tunnel_help.setWordWrap(True)
        client_tunnel_layout.addWidget(self.client_tunnel_help)
        row = QHBoxLayout()
        for source, callback in (
            ('Connect WireGuard client', self.connect_wireguard_client),
            ('Disconnect WireGuard', self.disconnect_wireguard),
        ):
            button = QPushButton(self.client_tunnel_group)
            button.clicked.connect(callback)
            row.addWidget(button)
            self.buttons[source] = button
        client_tunnel_layout.addLayout(row)
        connect_layout.addWidget(self.client_tunnel_group)
        connect_layout.addStretch(1)
        self.mode_tabs.addTab(self.connect_tab, '')

        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.retranslate()

    def _root(self):
        if self.directory is not None:
            return self.directory
        return vpn_data_directory()

    def _open(self, create=False, cidr=None):
        root = self._root()
        metadata = root / 'network.json'
        if metadata.exists():
            identities = identity_store(root / 'identities')
            if metadata.stat().st_size > 1024:
                raise ValueError('Invalid VPN metadata.')
            data = json.loads(metadata.read_text(encoding='utf-8'))
            network = str(validate_network(data['cidr']))
            identity = identities.load('server')
        elif create:
            identities = identity_store(root / 'identities')
            network = str(validate_network(cidr))
            try:
                identity = identities.load('server')
            except FileNotFoundError:
                identity = identities.create('server')
            # Exclusive metadata creation preserves an existing network.
            descriptor, temporary = tempfile.mkstemp(prefix='.network-', dir=root)
            try:
                with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                    json.dump({'cidr': network}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, metadata)
            finally:
                os.unlink(temporary)
        else:
            return None
        return VPNRegistry(root / 'registry.sqlite', network, identity.public_key)

    def _run(self, operation, kind):
        if self.busy:
            return
        self.busy = True
        self.kind = kind
        self.update_actions()
        self.task = _Task(operation)
        self.task.signals.finished.connect(self._finished)
        QThreadPool.globalInstance().start(self.task)

    def _finished(self, result, error):
        self.busy = False
        if self.closing:
            return
        diagnostics_updated = False
        if error:
            self.message_source = error
        elif self.kind in ('prepare', 'refresh'):
            self.registry, self.rows, self.diagnostics = result[:3]
            diagnostics_updated = True
            if len(result) > 3:
                self.tunnel_status = result[3]
            self.loaded = True
            if self.registry:
                self.cidr.setText(self.registry.cidr)
            self.message_source = 'Local network prepared. VPN connection is not active.' if self.registry else 'No local VPN network prepared.'
        elif self.kind in ('invite', 'remote_invite'):
            self.show_invite(result)
            self.message_source = 'Remote invitation generated. VPN tunnel is not active.' if self.kind == 'remote_invite' else 'Local invitation generated. Use a remote invitation to enroll another computer.'
        elif self.kind == 'server_start':
            self.listener = result
            self.message_source = 'HTTPS enrollment started. VPN tunnel is not active.'
        elif self.kind == 'server_stop':
            self.listener = None
            self.message_source = 'HTTPS enrollment stopped.'
        elif self.kind == 'request':
            self.message_source = 'Enrollment request sent. Await local administrator approval; VPN tunnel is not active.'
        elif self.kind == 'tunnel_start':
            self.tunnel_status, self.tunnel_role = result
            self.tunnel_name = self.tunnel_status['name']
            self.message_source = 'WireGuard tunnel started. Refresh status to verify the peer handshake.'
        elif self.kind == 'tunnel_stop':
            self.message_source = 'WireGuard tunnel stopped.'
        elif self.kind == 'wireguard_install':
            self.message_source = 'WireGuard installer started. Complete installation, then refresh VPN status.'
        else:
            self.rows = result
            self.message_source = 'Local authorization updated. No active tunnel was modified.'
        self.retranslate()
        if diagnostics_updated:
            self._offer_wireguard_install()

    def _offer_wireguard_install(self):
        diagnostics = getattr(self, 'diagnostics', None)
        if (
            self.closing
            or self.wireguard_install_prompted
            or not wireguard_install_supported()
            or not diagnostics
            or diagnostics.get('binaries_found')
        ):
            return
        self.wireguard_install_prompted = True
        self.install_wireguard(confirm=True)

    def request_elevation(self):
        text = self.controller.language.text
        if QMessageBox.question(
            self,
            text('Administrator privileges required'),
            text('The VPN needs administrator privileges. Restart the app as administrator? '
                 'The server will be stopped and a password prompt will appear.'),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            self.elevation = relaunch_elevated()
        except OSError:
            self.elevation = None
        if self.elevation is None:
            self.message_source = 'Could not request administrator privileges.'
            self.retranslate()
            return
        self.elevate_button.setEnabled(False)
        self.message_source = 'Waiting for administrator approval...'
        self.retranslate()
        self.elevation_timer = QTimer(self)
        self.elevation_timer.timeout.connect(self._check_elevation)
        self.elevation_timer.start(500)

    def _check_elevation(self):
        # The administrator copy closes this window itself once it is visible.
        if self.elevation.poll() is None:
            return
        self.elevation_timer.stop()
        self.elevation = None
        self.message_source = 'Could not request administrator privileges.'
        self.retranslate()

    def install_wireguard(self, *, confirm=True):
        diagnostics = getattr(self, 'diagnostics', None)
        if (
            self.busy
            or not wireguard_install_supported()
            or (diagnostics and diagnostics.get('binaries_found'))
        ):
            return
        if confirm and QMessageBox.question(
            self,
            self.controller.language.text('Install WireGuard?'),
            self.controller.language.text(
                'WireGuard is not installed. Download the official installer and start installation? '
                'The Windows administrator approval prompt will appear.'
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self.wireguard_install_prompted = True
        self._run(install_wireguard_package, 'wireguard_install')

    def prepare(self):
        cidr = self.cidr.text()
        try:
            validate_network(cidr)
        except ValueError:
            self.message_source = 'Enter a private IPv4 network with prefix /16 through /29.'
            self.retranslate()
            return
        def operation():
            registry = self._open(True, cidr)
            return registry, registry.devices(), wireguard_diagnostics()
        self._run(operation, 'prepare')

    def refresh(self):
        def operation():
            registry = self._open()
            status = self.wireguard.status(self.tunnel_name) if self.wireguard and self.tunnel_name else None
            return registry, registry.devices() if registry else [], wireguard_diagnostics(), status
        self._run(operation, 'refresh')

    def invite(self):
        if self.registry:
            self._run(self.registry.create_invite, 'invite')

    def show_invite(self, invitation):
        text = self.controller.language.text
        remote = isinstance(invitation, RemoteInvite)
        dialog = QDialog(self)
        dialog.setWindowTitle(text('Local VPN invitation'))
        layout = QVBoxLayout(dialog)
        note = QLabel(text('Send this invitation through a trusted channel. Enrollment requires administrator approval and does not activate the VPN.') if remote else text('Local token only, valid for 15 minutes. Use a remote invitation to enroll another computer.'), dialog)
        note.setWordWrap(True)
        layout.addWidget(note)
        token = QPlainTextEdit(invitation.export() if remote else invitation.token, dialog)
        token.setReadOnly(True)
        token.setAccessibleName(text('Local VPN invitation'))
        layout.addWidget(token)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(540, 180)
        dialog.exec()
        token.clear()
        dialog.deleteLater()

    def start_enrollment(self):
        if self.registry is None or self.listener or self.busy:
            return
        text = self.controller.language.text
        cert, _ = QFileDialog.getOpenFileName(self, text('Select public TLS certificate'), '', 'PEM (*.pem *.crt);;All files (*)')
        if not cert:
            return
        key, _ = QFileDialog.getOpenFileName(self, text('Select existing TLS private key'), '', 'PEM (*.pem *.key);;All files (*)')
        if not key:
            return
        host, accepted = QInputDialog.getText(self, text('Start HTTPS enrollment'), text('Listen on IPv4 address:'), text='127.0.0.1')
        if not accepted:
            return
        port, accepted = QInputDialog.getInt(self, text('Start HTTPS enrollment'), text('HTTPS enrollment port:'), 8444, 1024, 65535)
        if not accepted:
            return
        registry = self.registry
        def operation():
            listener = AdmissionServer(registry, cert, key, host=host, port=port).start()
            self.listener = listener
            if self.closing:
                listener.stop()
            return listener
        self._run(operation, 'server_start')

    def stop_enrollment(self):
        if self.listener:
            self._run(self.listener.stop, 'server_stop')

    def shutdown(self):
        self.closing = True
        if self.listener:
            self.listener.stop()
        if self.wireguard and self.tunnel_name:
            self._stop_tunnel()

    def remote_invite(self):
        if self.listener is None or self.busy:
            return
        text = self.controller.language.text
        host, accepted = QInputDialog.getText(self, text('Generate remote invitation'), text('Server hostname or IP matching the TLS certificate:'), text='127.0.0.1')
        if accepted:
            self._run(lambda: self.listener.create_invite(host), 'remote_invite')

    def send_request(self):
        if self.busy:
            return
        text = self.controller.language.text
        payload, accepted = QInputDialog.getMultiLineText(self, text('Send enrollment request'), text('Paste the VPN invitation JSON:'))
        if not accepted:
            return
        try:
            invite = RemoteInvite.parse(payload)
        except ValueError:
            self.message_source = 'Invalid or expired remote VPN invitation.'
            self.retranslate()
            return
        name, accepted = QInputDialog.getText(self, text('Send enrollment request'), text('Device name:'))
        if not accepted:
            return
        def operation():
            identities = identity_store(self._root() / 'identities')
            try:
                identity = identities.load('client')
            except FileNotFoundError:
                identity = identities.create('client')
            return request_remote_admission(invite, identity.public_key, name)
        self._run(operation, 'request')

    def change_device(self, action):
        row = self.table.currentRow()
        if self.registry is None or row < 0:
            return
        device = self.table.item(row, 0).data(Qt.UserRole)
        registry = self.registry
        def operation():
            if self.tunnel_role == 'server':
                self._stop_tunnel()  # Fail closed before changing peer authorization.
            getattr(registry, action)(device['id'])
            return registry.devices()
        self._run(operation, 'device')

    def _runtime(self):
        if self.wireguard is None:
            self.wireguard = tunnel_backend()
        return self.wireguard

    def _stop_tunnel(self):
        if self.tunnel_name and self.wireguard:
            self.wireguard.stop(self.tunnel_name)
        self.tunnel_name = self.tunnel_role = self.tunnel_status = None

    def start_wireguard_server(self):
        if self.busy or self.registry is None:
            return
        text = self.controller.language.text
        port, accepted = QInputDialog.getInt(self, text('Start WireGuard server'), text('WireGuard UDP port:'), self.server_udp_port, 1024, 65535)
        if not accepted:
            return
        self.server_udp_port = port
        def operation():
            runtime = self._runtime()
            self._stop_tunnel()
            identity = identity_store(self._root() / 'identities').load('server')
            status = runtime.start_server(identity, self.registry.cidr, port, self.registry.authorized_peers())
            # Retain ownership immediately, even if the app closes before its
            # worker result is dispatched to the GUI.
            self.tunnel_name, self.tunnel_role = status['name'], 'server'
            if self.closing:
                self._stop_tunnel()
            return status, 'server'
        self._run(operation, 'tunnel_start')

    def export_connection(self):
        row = self.table.currentRow()
        if self.registry is None or row < 0 or self.busy:
            return
        device = self.table.item(row, 0).data(Qt.UserRole)
        if device['state'] != 'approved':
            return
        text = self.controller.language.text
        host, accepted = QInputDialog.getText(self, text('Export client connection'), text('WireGuard server hostname or IP:'))
        if not accepted:
            return
        port, accepted = QInputDialog.getInt(self, text('Export client connection'), text('WireGuard UDP port:'), self.server_udp_port, 1024, 65535)
        if not accepted:
            return
        try:
            profile = ClientConnection(self.registry.cidr, device['address'], device['public_key'], self.registry.server_public_key, host, port)
            payload = profile.export()
        except ValueError:
            self.message_source = 'Invalid WireGuard connection profile.'
            self.retranslate()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(text('Export client connection'))
        layout = QVBoxLayout(dialog)
        note = QLabel(text('Send this public profile through the same trusted channel as the invitation. No private key is included.'), dialog)
        note.setWordWrap(True)
        layout.addWidget(note)
        content = QPlainTextEdit(payload, dialog)
        content.setReadOnly(True)
        layout.addWidget(content)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(600, 300)
        dialog.exec()
        dialog.deleteLater()

    def connect_wireguard_client(self):
        if self.busy:
            return
        text = self.controller.language.text
        payload, accepted = QInputDialog.getMultiLineText(self, text('Connect WireGuard client'), text('Paste the approved client connection JSON:'))
        if not accepted:
            return
        try:
            connection = ClientConnection.parse(payload)
        except ValueError:
            self.message_source = 'Invalid WireGuard connection profile.'
            self.retranslate()
            return
        def operation():
            runtime = self._runtime()
            identity = identity_store(self._root() / 'identities').load('client')
            # Validate identity/profile before taking down an existing tunnel.
            from ..core.vpn_service import render_client_config
            render_client_config(identity, connection)
            self._stop_tunnel()
            status = runtime.start_client(identity, connection)
            self.tunnel_name, self.tunnel_role = status['name'], 'client'
            if self.closing:
                self._stop_tunnel()
            return status, 'client'
        self._run(operation, 'tunnel_start')

    def disconnect_wireguard(self):
        if not self.busy and self.tunnel_name:
            self._run(self._stop_tunnel, 'tunnel_stop')

    def review_invite(self):
        text = self.controller.language.text
        payload, accepted = QInputDialog.getMultiLineText(
            self, text('Review remote invitation'), text('Paste the VPN invitation JSON:'))
        if not accepted:
            return
        try:
            invite = RemoteInvite.parse(payload)
        except ValueError:
            self.message_source = 'Invalid or expired remote VPN invitation.'
            self.retranslate()
            return
        message = text('Invitation validated locally. No request was sent. Use Send enrollment request to submit it explicitly.')
        message += f'\n\n{invite.host}:{invite.port}\nSHA-256: {invite.certificate_sha256}'
        QMessageBox.information(self, text('Review remote invitation'), message)

    def update_actions(self):
        enabled = not self.busy
        self.buttons['Prepare local VPN network'].setEnabled(enabled and self.registry is None)
        self.buttons['Refresh VPN status'].setEnabled(enabled)
        self.buttons['Generate local invitation'].setEnabled(enabled and self.registry is not None)
        self.cidr.setEnabled(enabled and self.registry is None)
        self.review_button.setEnabled(enabled)
        self.buttons['Start HTTPS enrollment'].setEnabled(enabled and self.registry is not None and self.listener is None)
        self.buttons['Stop HTTPS enrollment'].setEnabled(enabled and self.listener is not None)
        self.buttons['Generate remote invitation'].setEnabled(enabled and self.listener is not None)
        self.buttons['Send enrollment request'].setEnabled(enabled)
        self.buttons['Start WireGuard server'].setEnabled(enabled and self.registry is not None)
        self.buttons['Connect WireGuard client'].setEnabled(enabled)
        self.buttons['Disconnect WireGuard'].setEnabled(enabled and self.tunnel_name is not None)
        diagnostics = getattr(self, 'diagnostics', None)
        show_installer = (
            wireguard_install_supported()
            and diagnostics is not None
            and not diagnostics.get('binaries_found')
        )
        self.install_wireguard_button.setVisible(show_installer)
        self.install_wireguard_button.setEnabled(enabled and show_installer)
        self.elevate_button.setVisible(elevation_available())
        self.elevate_button.setEnabled(enabled)
        row = self.table.currentRow()
        state = self.table.item(row, 0).data(Qt.UserRole)['state'] if row >= 0 and self.table.item(row, 0) else None
        self.buttons['Export client connection'].setEnabled(enabled and self.registry is not None and state == 'approved')
        for source, required in (('Approve device locally', 'pending'), ('Reject device locally', 'pending'), ('Revoke local authorization', 'approved')):
            self.buttons[source].setEnabled(enabled and state == required)

    def retranslate(self):
        text = self.controller.language.text
        self.network_group.setTitle(text('WireGuard installation and status'))
        self.create_network_group.setTitle(text('Create a network: choose its private address range'))
        self.enrollment_group.setTitle(text('Invite and approve devices'))
        self.tunnel_group.setTitle(text('Start the server and share client access'))
        self.devices_group.setTitle(text('Registered devices'))
        self.client_enrollment_group.setTitle(text('Request access to an existing network'))
        self.client_tunnel_group.setTitle(text('Connect to an existing network'))
        self.mode_tabs.setTabText(
            self.mode_tabs.indexOf(self.create_tab), text('Create a network')
        )
        self.mode_tabs.setTabText(
            self.mode_tabs.indexOf(self.connect_tab), text('Connect to a network')
        )
        try:
            platform = vpn_platform()
        except WireGuardError:
            platform = 'unsupported'
        source = ('WireGuard tunnels require the official Windows installation and an administrator session. Internet and remote LAN routing remain disabled.' if platform == 'windows' else
                  'Linux VPN requires administrative privileges, systemd-creds and WireGuard tools. Internet and remote LAN routing remain disabled.' if platform == 'linux' else
                  'VPN integration supports Windows and Linux only.')
        self.note.setText(text(source))
        self.install_wireguard_button.setText(text('Install WireGuard'))
        self.elevate_button.setText(text('Restart as administrator'))
        self.enrollment_help.setText(text(
            'Start HTTPS enrollment, create a remote invitation, and send it securely. '
            'Approve the request from the other device in the list below.'
        ))
        self.tunnel_help.setText(text(
            'After approving a device, start the WireGuard server. Select the approved device '
            'below to export its client connection. Restart the server after changing approvals.'
        ))
        self.client_enrollment_help.setText(text(
            'Get an invitation from the network administrator, then send a registration request. '
            'The administrator must approve your device before sending you a connection profile.'
        ))
        self.client_tunnel_help.setText(text(
            'After approval, paste the connection profile provided by the administrator. '
            'The client and server must both be running and able to reach each other.'
        ))
        self.guide.setText(text(self._next_step()))
        status = self.tunnel_status or {}
        source = ('WireGuard handshake confirmed.' if status.get('handshake_verified') else
                  'WireGuard tunnel active; waiting for a peer handshake.' if status.get('service_running') else
                  'No WireGuard tunnel started by this session.')
        self.tunnel_label.setText(text(source))
        self.cidr_label.setText(text('VPN network:'))
        self.review_button.setText(text('Review remote invitation'))
        self.cidr.setAccessibleName(text('VPN network:'))
        for source, button in self.buttons.items():
            button.setText(text(source))
        self.table.setHorizontalHeaderLabels([text('Device'), text('Status'), text('Virtual IP')])
        self.table.setAccessibleName(text('VPN devices'))
        rows = getattr(self, 'rows', [])
        self.table.setRowCount(0)
        for row, device in enumerate(rows):
            self.table.insertRow(row)
            for column, value in enumerate((device['name'], text(device['state']), device['address'] or '—')):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, device)
                    item.setToolTip(device['public_key'])
                self.table.setItem(row, column, item)
        diagnostics = getattr(self, 'diagnostics', None)
        self.diagnostic.setText(text('WireGuard binaries found.') if diagnostics and diagnostics['binaries_found'] else text('WireGuard binaries not detected.'))
        self.status.setText(text(self.message_source) if self.message_source else '')
        self.update_actions()

    def _next_step(self):
        rows = getattr(self, 'rows', [])
        approved = sum(device['state'] == 'approved' for device in rows)
        status = self.tunnel_status or {}
        if self.tunnel_role == 'server' and status.get('service_running'):
            if status.get('handshake_verified'):
                return 'Next: select an approved device, export its client connection, and use it on that device. The handshake confirms at least one peer.'
            if approved:
                return 'Server tunnel is running. Select an approved device, export its connection, send it securely, then connect from that device and refresh status.'
            return 'Server tunnel is running, but no device is approved yet. Start HTTPS enrollment below, send an invitation, approve the request, then restart the server tunnel.'
        if self.tunnel_role == 'client' and status.get('service_running'):
            if status.get('handshake_verified'):
                return 'Client tunnel connected. Use the VPN server address to access its services; refresh status if needed.'
            return 'Client tunnel is running. Check that the server is running, the endpoint and UDP port are reachable, then refresh status to check the handshake.'
        if self.registry is None:
            return 'Choose a mode: create a network on the server, or switch to Connect to a network to join one using an invitation from its administrator.'
        if self.listener is None:
            return 'Network is ready. On the server, start HTTPS enrollment and generate a remote invitation so another computer can request access.'
        if approved:
            return 'An approved device is ready. Start or restart the server tunnel, select that device, and export its connection.'
        return 'HTTPS enrollment is active. Generate a remote invitation and send it to the other computer; approve its request here when it appears.'
