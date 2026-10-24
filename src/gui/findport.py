"""FindPort port inventory and explicit, asynchronous system management actions."""

import re
import sys

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMessageBox, QDialog, QPlainTextEdit, QDialogButtonBox, QStyle,
)

from ..core.findport import invoke, can_stop, audit_text


class _Signals(QObject):
    finished = Signal(bool, object)


class _FindPortTask(QRunnable):
    def __init__(self, action, item=None):
        super().__init__()
        self.action, self.item = action, item
        self.signals = _Signals()

    def run(self):
        try:
            result = (True, audit_text()) if self.action == 'Audit' else invoke(self.action, self.item)
        except Exception as error:
            result = False, str(error)
        self.signals.finished.emit(*result)


class FindPortPanel(QWidget):
    HEADERS = ('Port', 'Protocol', 'Local address', 'PID', 'Process', 'Exposure', 'Category', 'Known service', 'FindPort rule')
    VALUES = {
        'Local (PC)': 'Local only', 'Rede / Aberta': 'Network binding',
        'Sistema Critico': 'Protected process', 'Dev / Servidor Local': 'Development server',
        'Aplicativo de Usuario': 'User application', 'Servico do Windows': 'Windows service',
        'Aplicativo / Terceiros': 'Third-party application', 'Outro': 'Other',
        'Processo essencial do Windows': 'Essential Windows process',
        'Servidor local ou ferramenta de desenvolvimento': 'Local server or development tool',
        'Aplicativo em segundo plano': 'Background application',
        'Servico de rede/compartilhamento': 'Network or sharing service',
        'Aplicativo terceiro': 'Third-party application',
        'Aplicativo de usuario (Voz/Streaming/Jogos)': 'User application (voice, streaming or games)',
        'Servico do Windows (DNS/DHCP/SSDP)': 'Windows service (DNS/DHCP/SSDP)',
        'Endpoint UDP terceiro': 'Third-party UDP endpoint',
        'FTP (Transferencia de arquivos)': 'FTP (File transfer)',
        'SSH (Acesso remoto seguro)': 'SSH (Secure remote access)',
        'DNS (Resolucao de nomes)': 'DNS (Name resolution)',
        'HTTP (Servidor Web)': 'HTTP (Web server)',
        'RPC (Chamada de Procedimento Windows)': 'RPC (Windows remote procedure call)',
        'HTTPS (Web Seguro / SSL)': 'HTTPS (Secure web / SSL)',
        'SMB (Compartilhamento de Arquivos Windows)': 'SMB (Windows file sharing)',
        'RDP (Area de Trabalho Remota)': 'RDP (Remote desktop)',
        'AnyDesk (Acesso Remoto)': 'AnyDesk (Remote access)',
        'HTTP Alternativo / Apache Tomcat / Dev': 'Alternate HTTP / Apache Tomcat / Dev',
    }

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.ports, self.rules, self.warnings = [], [], []
        self.loading = self.loaded = False
        self.status_source = 'Click Refresh to list local TCP and UDP ports.'
        self.error = ''
        self.notice = ''
        layout = QVBoxLayout(self)
        description = QLabel('Inspect local listening ports and manage FindPort firewall rules. A network binding does not prove internet access. Ending a process closes its entire application.', self)
        description.setWordWrap(True)
        layout.addWidget(description)
        filters = QHBoxLayout()
        self.search = QLineEdit(self)
        search_palette = self.search.palette()
        search_palette.setColor(QPalette.PlaceholderText, QColor('#b8c1cc'))
        self.search.setPalette(search_palette)
        self.search.setPlaceholderText('Search port, process, service or address...')
        self.protocol = QComboBox(self)
        for title, value in (('All protocols', ''), ('TCP', 'TCP'), ('UDP', 'UDP')):
            self.protocol.addItem(title, value)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.protocol)
        layout.addLayout(filters)
        self.hide_protected = QCheckBox('Hide protected processes', self)
        layout.addWidget(self.hide_protected)
        self.table = self.make_table(len(self.HEADERS))
        self.table.setObjectName('findport_ports')
        self.table.setMinimumHeight(220)
        layout.addWidget(self.table)
        self.details = QLabel(self)
        self.details.setTextFormat(Qt.PlainText)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.details)
        controls = QHBoxLayout()
        self.refresh_button = self.button('Refresh', QStyle.SP_BrowserReload, self.refresh)
        self.server_button = self.button('Find server port', QStyle.SP_FileDialogContentsView, self.find_server)
        self.audit_button = self.button('Audit log', QStyle.SP_FileDialogDetailedView, lambda: self.start('Audit'))
        for button in (self.refresh_button, self.server_button, self.audit_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        actions = QHBoxLayout()
        self.block_button = self.button('Block port', QStyle.SP_MessageBoxWarning, lambda: self.manage('Block'))
        self.stop_button = self.button('End process', QStyle.SP_BrowserStop, lambda: self.manage('Stop'))
        actions.addWidget(self.block_button)
        actions.addWidget(self.stop_button)
        layout.addLayout(actions)
        rules_title = QLabel('Rules created by FindPort', self)
        layout.addWidget(rules_title)
        self.rules_table = self.make_table(5)
        self.rules_table.setObjectName('findport_rules')
        self.rules_table.setMinimumHeight(120)
        layout.addWidget(self.rules_table)
        self.unblock_button = self.button('Remove selected block rule', QStyle.SP_DialogApplyButton, lambda: self.manage('Unblock'))
        layout.addWidget(self.unblock_button)
        self.status = QLabel(self)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.search.textChanged.connect(self.render_ports)
        self.protocol.currentIndexChanged.connect(self.render_ports)
        self.hide_protected.toggled.connect(self.render_ports)
        self.table.itemSelectionChanged.connect(self.update_actions)
        self.rules_table.itemSelectionChanged.connect(self.update_actions)
        self.labels = controller.language.capture(self)
        self.retranslate()

    def make_table(self, columns):
        table = QTableWidget(0, columns, self)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSortingEnabled(True)
        return table

    def button(self, title, icon, callback):
        button = QPushButton(self.style().standardIcon(icon), title, self)
        button.setMinimumHeight(44)
        button.clicked.connect(callback)
        return button

    @staticmethod
    def selected(table):
        if not table.selectionModel().hasSelection():
            return None
        cell = table.item(table.currentRow(), 0)
        return cell.data(Qt.UserRole) if cell else None

    def supported(self):
        return self.controller.windows_share_supported or sys.platform.startswith('linux')

    def update_actions(self):
        available = self.supported() and not self.loading
        item = self.selected(self.table)
        self.refresh_button.setEnabled(available)
        self.server_button.setEnabled(available)
        self.audit_button.setEnabled(available)
        self.block_button.setEnabled(available and item is not None)
        self.stop_button.setEnabled(available and bool(item and can_stop(item)))
        self.unblock_button.setEnabled(available and self.selected(self.rules_table) is not None)
        reason = str(item.get('Motivo') or '') if item else ''
        reason = self.controller.language.text(self.VALUES.get(reason, reason))
        self.details.setText((str(item.get('Caminho') or '') + '\n' + reason) if item else '')

    def refresh(self):
        self.start('Snapshot')

    def start(self, action, item=None):
        if self.loading or not self.supported():
            return
        self.loading = self.loaded = True
        self.error = ''
        self.status_source = 'Reading ports and firewall rules...' if action == 'Snapshot' else 'Running FindPort operation...'
        self.retranslate_status()
        self.update_actions()
        self.task = _FindPortTask(action, dict(item) if item else None)
        self.task.signals.finished.connect(self.finished)
        QThreadPool.globalInstance().start(self.task)

    def finished(self, ok, result):
        action = self.task.action
        self.loading = False
        if not ok:
            if action == 'Snapshot':
                self.ports, self.rules, self.warnings = [], [], []
                self.render_ports()
                self.render_rules()
            self.status_source = 'FindPort operation failed.'
            self.error = str(result)
        elif action == 'Snapshot':
            self.ports, self.rules, self.warnings = result['ports'], result['rules'], result['warnings']
            self.status_source = 'Port list updated.'
            self.render_ports()
            self.render_rules()
        elif action == 'Audit':
            dialog = QDialog(self)
            dialog.setWindowTitle(self.controller.language.text('Audit log'))
            dialog.resize(780, 440)
            layout = QVBoxLayout(dialog)
            text = QPlainTextEdit(dialog)
            text.setReadOnly(True)
            text.setPlainText(result or self.controller.language.text('No audit entries yet.'))
            layout.addWidget(text)
            buttons = QDialogButtonBox(QDialogButtonBox.Close, dialog)
            buttons.button(QDialogButtonBox.Close).setText(self.controller.language.text('Close'))
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            self.status_source = 'Audit log opened.'
            dialog.exec()
        else:
            self.notice = 'Operation completed.'
            self.refresh()
            return
        self.retranslate_status()
        self.update_actions()

    def find_server(self):
        server = self.controller.server_manager.httpd
        port = server.server_address[1] if server is not None else self.controller.window.line_port.text().strip()
        if not str(port).isascii() or not str(port).isdigit() or not 1 <= int(port) <= 65535:
            self.status_source = 'Choose a valid server port or start the server first.'
            self.retranslate_status()
            return
        self.protocol.setCurrentIndex(self.protocol.findData('TCP'))
        self.hide_protected.setChecked(False)
        self.search.setText(str(port))
        self.refresh()

    def manage(self, action):
        if self.loading:
            return
        item = self.selected(self.rules_table if action == 'Unblock' else self.table)
        if not item or (action == 'Stop' and not can_stop(item)):
            return
        language = self.controller.language
        messages = {
            'Block': 'Block incoming {protocol} connections on port {port} on all interfaces? The application will keep running.',
            'Unblock': 'Remove the FindPort block rule for {protocol} port {port}? Other firewall rules remain in effect.',
            'Stop': 'End process {name} (PID {pid})? Its entire application will close and unsaved work may be lost.',
        }
        message = language.text(messages[action], protocol=item['Proto'], port=item['Porta'], name=item.get('Processo', ''), pid=item.get('PID', ''))
        answer = QMessageBox.question(self, 'FindPort', message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.notice = ''
            self.start(action, item)

    @staticmethod
    def fill(table, rows):
        previous = FindPortPanel.selected(table)
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for row, (values, item) in enumerate(rows):
            table.insertRow(row)
            for column, value in enumerate(values):
                cell = QTableWidgetItem()
                cell.setData(Qt.DisplayRole, value)
                cell.setToolTip(str(value))
                cell.setData(Qt.UserRole, item)
                table.setItem(row, column, cell)
            if previous and all(previous.get(key) == item.get(key) for key in ('Porta', 'Proto', 'Endereco', 'PID', 'Inicio')):
                table.selectRow(row)
        table.setSortingEnabled(True)

    def render_ports(self):
        language = self.controller.language
        term, protocol = self.search.text().strip().casefold(), self.protocol.currentData()
        rows = []
        for item in self.ports:
            if protocol and item['Proto'] != protocol:
                continue
            if self.hide_protected.isChecked() and not can_stop(item):
                continue
            exposure = language.text(self.VALUES.get(item['Exposicao'], item['Exposicao']))
            category = language.text(self.VALUES.get(item['Categoria'], item['Categoria']))
            rule = 'Unknown' if self.warnings else 'None'
            for existing in self.rules:
                if existing['RuleName'] == f"FindPort_Block_{item['Proto']}_{item['Porta']}":
                    rule = 'Enabled' if str(existing['Enabled']).lower() in ('true', '1') else 'Disabled'
            service = language.text(self.VALUES.get(item['Servico'], item['Servico']))
            values = (item['Porta'], item['Proto'], item['Endereco'], item['PID'], item['Processo'], exposure, category, service, language.text(rule))
            if term and term not in ' '.join(map(str, values)).casefold():
                continue
            rows.append((values, item))
        self.fill(self.table, rows)
        self.update_actions()

    def render_rules(self):
        rows = []
        for rule in self.rules:
            match = re.fullmatch(r'FindPort_Block_(TCP|UDP)_([0-9]+)', rule['RuleName'])
            if not match or not 1 <= int(match[2]) <= 65535:
                continue
            item = {'Proto': match[1], 'Porta': int(match[2])}
            enabled = self.controller.language.text('Enabled' if str(rule['Enabled']).lower() in ('true', '1') else 'Disabled')
            rows.append(((item['Porta'], item['Proto'], enabled, rule['RuleName'], rule.get('Descricao') or ''), item))
        self.fill(self.rules_table, rows)
        self.update_actions()

    def retranslate_status(self):
        language = self.controller.language
        source = self.status_source if self.supported() else 'FindPort requires Windows 10 or 11.'
        parts = [language.text(self.notice), language.text(source), language.text(self.error)]
        if self.warnings:
            parts += [language.text('Firewall rules could not be read. Their state is unknown.'), *self.warnings]
        self.status.setText('\n'.join(part for part in parts if part))

    def retranslate(self):
        language = self.controller.language
        language.apply(self.labels)
        self.protocol.setItemText(0, language.text('All protocols'))
        self.table.setHorizontalHeaderLabels([language.text(s) for s in self.HEADERS])
        self.rules_table.setHorizontalHeaderLabels([language.text(s) for s in ('Port', 'Protocol', 'State', 'Rule name', 'Description')])
        self.render_ports()
        self.render_rules()
        self.retranslate_status()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.loaded:
            self.refresh()
