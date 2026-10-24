"""Local creation, copying and revocation of expiring file download links."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QComboBox, QSpinBox, QCheckBox, QPushButton, QFileDialog, QDialogButtonBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from ..core.temp_links import DOWNLOAD_PREFIX, LinkError


class CreateLinkDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.language = controller.language
        self.token = None
        self.session_store = controller.server_manager.links
        self.setWindowTitle(self.language.text('Create temporary link'))
        self.resize(560, 300)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.source = QComboBox(self)
        server = controller.server_manager.httpd
        if server is not None:
            self.source.addItem(self.language.text('Main folder'), server.explorer)
            for name, explorer in server.shared_explorers.items():
                self.source.addItem(name, explorer)
        form.addRow(self.language.text('Shared folder:'), self.source)
        self.filename = QLineEdit(self)
        self.filename.setReadOnly(True)
        browse = QPushButton('...', self)
        browse.clicked.connect(self.browse)
        row = QHBoxLayout()
        row.addWidget(self.filename)
        row.addWidget(browse)
        form.addRow(self.language.text('File:'), row)
        self.lifetime = QSpinBox(self)
        self.lifetime.setRange(1, 10080)
        self.lifetime.setValue(60)
        self.lifetime.setSuffix(' min')
        form.addRow(self.language.text('Valid for:'), self.lifetime)
        self.require_password = QCheckBox(self.language.text('Require a link password'), self)
        form.addRow(self.require_password)
        self.password = QLineEdit(self)
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setMaxLength(256)
        self.password.setEnabled(False)
        self.require_password.toggled.connect(self.password.setEnabled)
        form.addRow(self.language.text('Link password:'), self.password)
        self.source.currentIndexChanged.connect(self.filename.clear)
        layout.addLayout(form)
        note = QLabel(self.language.text('Only the selected file can be downloaded. Editing or replacing that file invalidates its link. Stopping the server ends all links.'), self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.PlainText)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Ok).setText(self.language.text('Create link'))
        buttons.button(QDialogButtonBox.Cancel).setText(self.language.text('Cancel'))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse(self):
        explorer = self.source.currentData()
        if explorer is not None:
            path, _ = QFileDialog.getOpenFileName(self, self.language.text('Select file'), str(explorer.root))
            if path:
                self.filename.setText(path)

    def accept(self):
        if self.controller.server_manager.links is not self.session_store:
            self.error.setText(self.language.text('The server session changed. Reopen the link dialog.'))
            return
        if not self.controller.server_manager.is_running or self.source.currentData() is None:
            self.error.setText(self.language.text('Start the server to create temporary links.'))
            return
        password = self.password.text() if self.require_password.isChecked() else None
        try:
            self.token = self.controller.server_manager.links.create(
                self.source.currentData(), self.filename.text(), self.lifetime.value() * 60,
                password=password, source='Main folder' if self.source.currentIndex() == 0 else self.source.currentText(),
            )
        except LinkError as error:
            self.error.setText(self.language.text(str(error)))
            return
        self.password.clear()
        super().accept()


class TemporaryLinksPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.items = {}
        self.status_source = ''
        layout = QVBoxLayout(self)
        note = QLabel('A temporary link grants access to one file without the server login. Anyone with the link and its password, when configured, can download until expiry. Server IP restrictions still apply.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 6, self)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setMinimumHeight(160)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self.create_button = QPushButton('Create link', self)
        self.copy_button = QPushButton('Copy link', self)
        self.qr_button = QPushButton('QR Code', self)
        self.revoke_button = QPushButton('Revoke link', self)
        for button in (self.create_button, self.copy_button, self.qr_button, self.revoke_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        note = QLabel('Links last from 1 minute to 7 days and are kept only for the current server session. Revocation blocks new downloads; a download already started may finish.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.create_button.clicked.connect(self.create_link)
        self.copy_button.clicked.connect(self.copy_link)
        self.qr_button.clicked.connect(self.show_qr)
        self.revoke_button.clicked.connect(self.revoke_link)
        self.table.itemSelectionChanged.connect(self.update_actions)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.labels = controller.language.capture(self)
        self.retranslate()

    def selected_token(self):
        if not self.table.selectionModel().hasSelection():
            return None
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.UserRole) if item is not None else None

    def selected_url(self):
        token = self.selected_token()
        item = self.items.get(token)
        base = self.controller.access_combo.currentData()
        if self.controller.server_manager.is_running and item and item['status'] == 'Valid' and base:
            return base.rstrip('/') + DOWNLOAD_PREFIX + token
        return None

    def update_actions(self):
        running = self.controller.server_manager.is_running
        ready = bool(self.selected_url())
        self.create_button.setEnabled(running)
        self.copy_button.setEnabled(ready)
        self.qr_button.setEnabled(ready)
        item = self.items.get(self.selected_token())
        self.revoke_button.setEnabled(running and bool(item and item['status'] == 'Valid'))

    def create_link(self):
        if not self.controller.server_manager.is_running:
            return
        dialog = CreateLinkDialog(self.controller, self)
        if dialog.exec():
            self.status_source = 'Link created. Copy the address or generate its QR Code.'
            self.refresh(dialog.token)

    def copy_link(self):
        url = self.selected_url()
        if url:
            self.controller.app.clipboard().setText(url)
            self.status_source = 'Link copied.'
            self.refresh()

    def show_qr(self):
        url = self.selected_url()
        if url:
            self.controller.show_qr_code(url, temporary=True)

    def revoke_link(self):
        token = self.selected_token()
        if token is not None:
            self.controller.server_manager.links.revoke(token)
            self.status_source = 'Link revoked.'
            self.refresh()

    def refresh(self, select_token=None):
        language = self.controller.language
        selected = select_token or self.selected_token()
        items = self.controller.server_manager.links.snapshot()
        self.items = {item['token']: item for item in items}
        self.table.setRowCount(len(items))
        base = self.controller.access_combo.currentData()
        for row, item in enumerate(items):
            remaining = max(0, int(item['remaining']))
            url = (base.rstrip('/') if base else '') + DOWNLOAD_PREFIX + item['token'] if item['status'] == 'Valid' else ''
            source = language.text('Main folder') if item['source'] == 'Main folder' else item['source']
            values = (item['name'], source, f'{remaining // 60} min {remaining % 60:02d} s',
                      language.text('Yes' if item['protected'] else 'No'), language.text(item['status']), url)
            for column, value in enumerate(values):
                cell = self.table.item(row, column)
                if cell is None:
                    cell = QTableWidgetItem()
                    self.table.setItem(row, column, cell)
                cell.setText(value)
                cell.setToolTip(value)
            self.table.item(row, 0).setData(Qt.UserRole, item['token'])
            if item['token'] == selected:
                self.table.selectRow(row)
        self.update_actions()
        source = (self.status_source or 'Select a link to copy its address or revoke it.') if self.controller.server_manager.is_running else 'Start the server to create temporary links.'
        self.status.setText(language.text(source))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def retranslate(self):
        language = self.controller.language
        language.apply(self.labels)
        self.table.setHorizontalHeaderLabels([language.text(s) for s in ('File', 'Shared folder', 'Remaining', 'Password', 'Status', 'Address')])
        self.refresh()
