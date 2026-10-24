"""Configure additional HTTP folders and their public URLs."""

import os
import re

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QGroupBox, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QCheckBox, QDialogButtonBox, QLabel, QPushButton, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from ..core.shares import SHARES_PREFIX, validate_shared_folders


class SharedFolderDialog(QDialog):
    def __init__(self, folders, language, parent=None, item=None):
        super().__init__(parent)
        self.folders, self.language, self.item = folders, language, item
        self.setWindowTitle(language.text('Additional HTTP folder'))
        self.resize(540, 240)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit((item or {}).get('name', ''), self)
        self.path = QLineEdit((item or {}).get('path', ''), self)
        browse = QPushButton('...', self)
        browse.clicked.connect(self.browse)
        row = QHBoxLayout()
        row.addWidget(self.path)
        row.addWidget(browse)
        form.addRow(language.text('URL name:'), self.name)
        form.addRow(language.text('Folder path:'), row)
        self.writable = QCheckBox(language.text('Allow changes in this folder'), self)
        self.writable.setChecked((item or {}).get('writable', False))
        form.addRow(self.writable)
        layout.addLayout(form)
        note = QLabel(language.text('Changes also require Allow file modification in the Files tab. All folders use the server authentication and IP restrictions.'), self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.PlainText)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Cancel).setText(language.text('Cancel'))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, self.language.text('Select Directory'), self.path.text())
        if path:
            self.path.setText(path)
            if not self.name.text():
                self.name.setText(re.sub('[^a-zA-Z0-9_-]', '-', os.path.basename(path)).strip('-')[:40] or 'files')

    def accept(self):
        self.value = {'name': self.name.text().strip(), 'path': self.path.text().strip(), 'writable': self.writable.isChecked()}
        candidates = [entry for entry in self.folders if entry is not self.item] + [self.value]
        try:
            validate_shared_folders(candidates)
        except ValueError as error:
            self.error.setText(self.language.text(str(error)))
            return
        super().accept()


class SharedFoldersPanel(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__('Additional HTTP folders', parent)
        self.controller = controller
        layout = QVBoxLayout(self)
        note = QLabel('Publish several folders at the same address. Each folder has its own URL and starts as read-only. Stop the server to change this list.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 4, self)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setMinimumHeight(150)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self.add_button = QPushButton('Add folder', self)
        self.edit_button = QPushButton('Edit', self)
        self.remove_button = QPushButton('Remove', self)
        for button in (self.add_button, self.edit_button, self.remove_button):
            row.addWidget(button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.open_button = QPushButton('Open in browser', self)
        self.qr_button = QPushButton('QR Code', self)
        row.addWidget(self.open_button)
        row.addWidget(self.qr_button)
        layout.addLayout(row)
        self.add_button.clicked.connect(lambda: self.edit_folder(False))
        self.edit_button.clicked.connect(lambda: self.edit_folder(True))
        self.remove_button.clicked.connect(self.remove_folder)
        self.open_button.clicked.connect(self.open_folder)
        self.qr_button.clicked.connect(self.show_qr)
        self.table.itemSelectionChanged.connect(self.update_actions)
        self.labels = controller.language.capture(self)
        self.reload()

    def selected_index(self):
        row = self.table.currentRow()
        if self.table.selectionModel().hasSelection() and 0 <= row < len(self.controller.shared_folders):
            return row
        return None

    def selected_url(self):
        row = self.selected_index()
        base = self.controller.access_combo.currentData()
        if row is not None and base and self.controller.server_manager.is_running:
            return base.rstrip('/') + SHARES_PREFIX + self.controller.shared_folders[row]['name'] + '/'
        return None

    def edit_folder(self, editing):
        if self.controller.server_manager.is_running:
            return
        index = self.selected_index() if editing else None
        if editing and index is None:
            return
        dialog = SharedFolderDialog(self.controller.shared_folders, self.controller.language, self,
                                    self.controller.shared_folders[index] if editing else None)
        if dialog.exec():
            if editing:
                self.controller.shared_folders[index] = dialog.value
            else:
                self.controller.shared_folders.append(dialog.value)
            self.controller.save_server_preferences()
            self.reload()

    def remove_folder(self):
        index = self.selected_index()
        if index is not None and not self.controller.server_manager.is_running:
            del self.controller.shared_folders[index]
            self.controller.save_server_preferences()
            self.reload()

    def open_folder(self):
        url = self.selected_url()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def show_qr(self):
        url = self.selected_url()
        if url:
            self.controller.show_qr_code(url)

    def reload(self):
        language = self.controller.language
        language.apply(self.labels)
        self.table.setHorizontalHeaderLabels([language.text(s) for s in ('URL name', 'Local path', 'Permission', 'Address')])
        selected = self.selected_index()
        self.table.setRowCount(0)
        for row, item in enumerate(self.controller.shared_folders):
            self.table.insertRow(row)
            for column, value in enumerate((item['name'], item['path'], language.text('Read and write' if item['writable'] else 'Read only'), SHARES_PREFIX + item['name'] + '/')):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.table.setItem(row, column, cell)
        if selected is not None and selected < self.table.rowCount():
            self.table.selectRow(selected)
        self.update_actions()

    def update_actions(self):
        selected = self.selected_index() is not None
        running = self.controller.server_manager.is_running
        self.add_button.setEnabled(not running)
        self.edit_button.setEnabled(not running and selected)
        self.remove_button.setEnabled(not running and selected)
        ready = selected and running and bool(self.controller.access_combo.currentData())
        self.open_button.setEnabled(ready)
        self.qr_button.setEnabled(ready)
        base = self.controller.access_combo.currentData() if running else None
        for row, item in enumerate(self.controller.shared_folders):
            permission = self.table.item(row, 2)
            address = self.table.item(row, 3)
            if permission is not None:
                writable = item['writable'] and self.controller.window.chk_allow_mod.isChecked()
                permission.setText(self.controller.language.text('Read and write' if writable else 'Read only'))
            if address is not None:
                url = (base.rstrip('/') if base else '') + SHARES_PREFIX + item['name'] + '/'
                address.setText(url)
                address.setToolTip(url)
