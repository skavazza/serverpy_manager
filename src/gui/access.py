"""Manage hashed accounts and a permission matrix for each published folder."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGroupBox, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QCheckBox, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QDialogButtonBox, QPushButton, QMessageBox, QStyle)

from ..core.access import PERMISSIONS, hash_password, validate_users

LABELS = ('View', 'Download', 'Upload', 'Edit', 'Delete')


class FolderUserDialog(QDialog):
    def __init__(self, controller, parent=None, account=None):
        super().__init__(parent)
        self.controller, self.account = controller, account
        text = controller.language.text
        self.setWindowTitle(text('Folder user'))
        self.resize(720, 400)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit((account or {}).get('name', ''), self)
        self.password = QLineEdit(self)
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText(text('Leave empty to keep the existing password.') if account else text('At least 8 characters.'))
        form.addRow(text('User name:'), self.name)
        form.addRow(text('Password:'), self.password)
        layout.addLayout(form)
        self.roots = ['/'] + [item['name'] for item in controller.shared_folders]
        self.table = QTableWidget(len(self.roots), 6, self)
        self.table.setHorizontalHeaderLabels([text('Folder')] + [text(label) for label in LABELS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for row, root in enumerate(self.roots):
            self.table.setItem(row, 0, QTableWidgetItem(text('Main folder') if root == '/' else root))
            for column, permission in enumerate(PERMISSIONS, 1):
                cell = QTableWidgetItem()
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
                cell.setCheckState(Qt.Checked if permission in (account or {}).get('grants', {}).get(root, []) else Qt.Unchecked)
                self.table.setItem(row, column, cell)
        layout.addWidget(self.table)
        note = QLabel(text('Changes also require the folder and server write switches. Rename/move require Edit and Delete; copy requires Download and Upload. Unchecked permissions are denied.'), self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.PlainText)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Cancel).setText(text('Cancel'))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        try:
            password = hash_password(self.password.text()) if self.password.text() or not self.account else self.account['password']
            grants = {root: [key for column, key in enumerate(PERMISSIONS, 1) if self.table.item(row, column).checkState() == Qt.Checked]
                      for row, root in enumerate(self.roots)}
            value = {'name': self.name.text().strip(), 'password': password, 'grants': grants}
            validate_users([entry for entry in self.controller.folder_users if entry is not self.account] + [value], self.roots)
            self.value = value
        except ValueError as error:
            self.error.setText(self.controller.language.text(str(error)))
            return
        super().accept()


class FolderAccessPanel(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox(self)
        layout.addWidget(self.enabled)
        self.note = QLabel(self)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.table = QTableWidget(0, 2, self)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self.buttons = {}
        for source, icon, callback in (
            ('Add user', QStyle.SP_FileDialogNewFolder, lambda: self.edit_user(False)),
            ('Edit', QStyle.SP_FileDialogDetailedView, lambda: self.edit_user(True)),
            ('Remove', QStyle.SP_TrashIcon, self.remove_user),
        ):
            button = QPushButton(self)
            button.setIcon(self.style().standardIcon(icon))
            button.clicked.connect(callback)
            row.addWidget(button)
            self.buttons[source] = button
        layout.addLayout(row)
        self.enabled.toggled.connect(self.changed)
        self.table.itemSelectionChanged.connect(self.update_actions)
        self.retranslate()

    def changed(self, enabled):
        self.controller.folder_users_enabled = enabled
        self.controller.save_server_preferences()

    def selected(self):
        row = self.table.currentRow()
        return row if self.table.selectionModel().hasSelection() and 0 <= row < len(self.controller.folder_users) else None

    def edit_user(self, editing):
        if self.controller.server_manager.is_running:
            return
        index = self.selected() if editing else None
        if editing and index is None:
            return
        dialog = FolderUserDialog(self.controller, self, self.controller.folder_users[index] if editing else None)
        if dialog.exec():
            if editing:
                self.controller.folder_users[index] = dialog.value
            else:
                self.controller.folder_users.append(dialog.value)
            self.controller.save_server_preferences()
            self.retranslate()

    def remove_user(self):
        index = self.selected()
        if index is None or self.controller.server_manager.is_running:
            return
        text = self.controller.language.text
        if QMessageBox.question(self, text('Folder users and permissions'), text('Remove this folder user?'), QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        del self.controller.folder_users[index]
        self.controller.save_server_preferences()
        self.retranslate()

    def update_actions(self):
        stopped = not self.controller.server_manager.is_running
        self.enabled.setEnabled(stopped)
        self.buttons['Add user'].setEnabled(stopped)
        for key in ('Edit', 'Remove'):
            self.buttons[key].setEnabled(stopped and self.selected() is not None)

    def retranslate(self):
        text = self.controller.language.text
        self.setTitle(text('Folder users and permissions'))
        self.enabled.blockSignals(True)
        self.enabled.setChecked(self.controller.folder_users_enabled)
        self.enabled.blockSignals(False)
        self.enabled.setText(text('Require individual users for folder access'))
        self.note.setText(text('Stop the server to edit accounts. Passwords are saved as salted hashes. The general login, when enabled, remains administrator. Folder roots must not overlap. These accounts do not grant camera or terminal access.'))
        self.table.setHorizontalHeaderLabels([text('User name'), text('Folders with permissions')])
        self.table.setRowCount(0)
        for row, user in enumerate(self.controller.folder_users):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(user['name']))
            self.table.setItem(row, 1, QTableWidgetItem(', '.join(root for root, allowed in user['grants'].items() if allowed)))
        for source, button in self.buttons.items():
            button.setText(text(source))
        self.update_actions()
