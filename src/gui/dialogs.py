from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QTextEdit, QFormLayout, QLineEdit, QDialogButtonBox,
    QTableWidget, QTableWidgetItem, QHBoxLayout, QHeaderView, QPushButton,
    QComboBox, QFileDialog, QMessageBox, QLabel, QCheckBox
)
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QTextCursor, QIcon
from .i18n import InterfaceLanguage

import os
import sys
import re
from collections import deque
from pathlib import Path
from ..core.response_headers import validate_response_headers
from ..project_info import get_project_info
import html


def get_app_icon_path() -> str | None:
    """
    Locate the absolute path to the application icon (server.svg).
    """
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "server.svg")
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "server.svg")
    candidates.append(Path(__file__).resolve().parents[2] / "server.svg")
    candidates.append(Path(__file__).resolve().parent / "server.svg")
    candidates.append(Path.cwd() / "server.svg")
    for p in candidates:
        if p.is_file():
            return str(p.resolve())
    return None


def get_app_icon() -> QIcon:
    """
    Load and return the QIcon for the application.
    """
    path = get_app_icon_path()
    return QIcon(path) if path else QIcon()


class AboutDialog(QDialog):
    def __init__(self, parent=None, language=None):
        super().__init__(parent)
        self.language = language or InterfaceLanguage()
        self.setWindowTitle(self.language.text('About'))
        self.resize(500, 300)

        icon = get_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        layout = QVBoxLayout(self)
        info = get_project_info()

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 6)
        if not icon.isNull():
            icon_label = QLabel(self)
            pixmap = icon.pixmap(48, 48)
            if not pixmap.isNull():
                icon_label.setPixmap(pixmap)
                icon_label.setScaledContents(True)
                icon_label.setFixedSize(48, 48)
                header_layout.addWidget(icon_label)

        title = QLabel(info['name'], self)
        title.setTextFormat(Qt.PlainText)
        title.setStyleSheet('font-size: 20px; font-weight: bold;')
        header_layout.addWidget(title)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        form = QFormLayout()
        self.fields = {}
        for label, key in (('Developer', 'developer'), ('Email', 'email'), ('WhatsApp', 'whatsapp'), ('License', 'license')):
            fallback = 'License not defined yet' if key == 'license' else 'Not provided'
            value = info.get(key) or self.language.text(fallback)
            if key == 'license' and info.get(key):
                value = self.language.text(value)
            field = QLabel(value, self)
            field.setTextFormat(Qt.PlainText)
            field.setWordWrap(True)
            field.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if key in ('email', 'whatsapp') and info.get(key):
                url = 'mailto:' + info['email'] if key == 'email' else info['whatsapp_url']
                field.setTextFormat(Qt.RichText)
                field.setText('<a href="' + html.escape(url, quote=True) + '">' + html.escape(value) + '</a>')
                field.setTextInteractionFlags(Qt.TextBrowserInteraction)
                field.setOpenExternalLinks(True)
            self.fields[key] = field
            form.addRow(self.language.text(label), field)
        credits = QLabel('\n'.join(info.get('credits', [])) or self.language.text('Not provided'), self)
        credits.setTextFormat(Qt.PlainText)
        credits.setWordWrap(True)
        form.addRow(self.language.text('Credits'), credits)
        details = QHBoxLayout()
        details.addLayout(form, 1)
        logo_path = Path(__file__).resolve().parents[2] / 'visual_identity' / 'krakenlogo.svg'
        if logo_path.is_file():
            logo = QLabel(self)
            logo.setObjectName('krakentech_logo')
            logo.setAccessibleName('KrakenTech Services')
            logo.setPixmap(QIcon(str(logo_path)).pixmap(128, 128))
            logo.setFixedSize(128, 128)
            logo.setAlignment(Qt.AlignCenter)
            details.addWidget(logo, 0, Qt.AlignRight | Qt.AlignTop)
        layout.addLayout(details)
        self.license_text = QTextEdit(self)
        self.license_text.setReadOnly(True)
        license_path = Path(__file__).resolve().parents[2] / 'LICENSE'
        if license_path.is_file():
            self.license_text.setPlainText(license_path.read_text(encoding='utf-8'))
            layout.addWidget(self.license_text)
            self.resize(560, 500)
        else:
            self.license_text.hide()
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText(self.language.text('Close'))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ResponseHeadersDialog(QDialog):
    def __init__(self, headers, parent=None, language=None):
        super().__init__(parent)
        self.language = language or InterfaceLanguage()
        self.setWindowTitle(self.language.text('Custom response headers'))
        self.resize(640, 420)

        icon = get_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        layout = QVBoxLayout(self)
        help_text = QLabel(self.language.text('Headers tell browsers how to handle responses. Examples: Cache-Control = no-store (avoid caching); X-Content-Type-Options = nosniff (prevent content type guessing). CORS and headers required for file delivery are configured by the server. Changes apply after restarting the server.'))
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels([self.language.text('Header name'), self.language.text('Value')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)
        for name, value in headers.items():
            self.add_row(name, value)
        row = QHBoxLayout()
        add = QPushButton(self.language.text('Add Row'))
        remove = QPushButton(self.language.text('Remove Selected'))
        add.clicked.connect(lambda: self.add_row())
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()) if self.table.currentRow() >= 0 else None)
        row.addWidget(add)
        row.addWidget(remove)
        layout.addLayout(row)
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        self.error.setStyleSheet('color: #ff9aa7;')
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Cancel).setText(self.language.text('Cancel'))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.headers = dict(headers)

    def add_row(self, name='', value=''):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        self.table.setItem(row, 1, QTableWidgetItem(value))

    def accept(self):
        rows = []
        for row in range(self.table.rowCount()):
            cells = [self.table.item(row, col) for col in range(2)]
            rows.append(tuple(cell.text() if cell else '' for cell in cells))
        try:
            self.headers = validate_response_headers(rows)
        except ValueError as error:
            self.error.setText(self.language.text(str(error)))
            return
        super().accept()

    def get_headers(self):
        return dict(self.headers)


class StreamIntercept(QObject):
    """
    Redirects stdout/stderr to a Qt Signal so it can be displayed in the UI,
    while preserving console output.
    """
    text_written = Signal(str)

    def __init__(self, original_stream=None):
        super().__init__()
        self.original_stream = original_stream

    def write(self, text):
        if self.original_stream:
            try:
                self.original_stream.write(text)
                self.original_stream.flush()
            except Exception:
                pass
        self.text_written.emit(text)
        return len(text)
        
    def flush(self):
        if self.original_stream:
            try:
                self.original_stream.flush()
            except Exception:
                pass


class LogWindow(QDialog):
    """
    A window to display real-time server logs.
    """
    def __init__(self, parent=None, language=None):
        super().__init__(parent)
        self.language = language or InterfaceLanguage()
        self.setWindowTitle("Server Logs")
        self.resize(600, 400)

        icon = get_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        layout = QVBoxLayout(self)
        self.entries = deque(maxlen=5000)
        self.pending_text = ''
        self.category = QComboBox(self)
        for title, code in (('All logs', 'all'), ('Access', 'access'), ('Errors', 'error'), ('Operations', 'operation')):
            self.category.addItem(title, code)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText('Filter logs...')
        controls = QHBoxLayout()
        controls.addWidget(self.category)
        controls.addWidget(self.search, 1)
        layout.addLayout(controls)
        self.log_text = QTextEdit(self)
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #1e1e1e; color: #dcdcdc; font-family: 'Courier New';")
        layout.addWidget(self.log_text)
        
        btn_clear = QPushButton("Clear Logs", self)
        btn_clear.clicked.connect(self.clear_logs)
        layout.addWidget(btn_clear)
        self.btn_export = QPushButton('Export logs', self)
        self.btn_export.clicked.connect(self.export_logs)
        layout.addWidget(self.btn_export)
        self.category.currentIndexChanged.connect(self.render_logs)
        self.search.textChanged.connect(self.render_logs)
        self.ui_translations = self.language.capture(self)
        self.retranslate()

    def retranslate(self):
        self.language.apply(self.ui_translations)
        self.category.blockSignals(True)
        for index, source in enumerate(('All logs', 'Access', 'Errors', 'Operations')):
            self.category.setItemText(index, self.language.text(source))
        self.category.blockSignals(False)

    @staticmethod
    def log_category(text):
        if re.search(r'"\s+[45]\d\d\b|code\s+[45]\d\d\b', text) or re.search(r'error|erro|exception|traceback|failed|falhou', text, re.IGNORECASE):
            return 'error'
        if re.search(r'"(?:GET|HEAD|OPTIONS)\s', text):
            return 'access'
        return 'operation'

    def append_log(self, text):
        combined = self.pending_text + text
        lines = combined.split('\n')
        self.pending_text = lines.pop()
        for line in lines:
            if line.strip(): self.entries.append((self.log_category(line), line))
        self.render_logs()

    def render_logs(self):
        category = self.category.currentData()
        term = self.search.text().casefold()
        entries = list(self.entries)
        if self.pending_text:
            entries.append((self.log_category(self.pending_text), self.pending_text))
        lines = [text for kind, text in entries if (category == 'all' or category == kind) and term in text.casefold()]
        self.log_text.setPlainText('\n'.join(lines))
        self.log_text.moveCursor(QTextCursor.End)
        self.log_text.ensureCursorVisible()

    def export_logs(self):
        path, _ = QFileDialog.getSaveFileName(self, self.language.text('Export logs'), 'serverpy-logs.txt', self.language.text('Text files (*.txt);;All Files (*)'))
        if path:
            try:
                Path(path).write_text(self.log_text.toPlainText(), encoding='utf-8')
            except OSError:
                QMessageBox.warning(self, self.language.text('Export logs'), self.language.text('Unable to export logs.'))
        
    def clear_logs(self):
        self.entries.clear()
        self.pending_text = ''
        self.log_text.clear()


class CORSDialog(QDialog):
    """
    Dialog for configuring CORS settings.
    """
    def __init__(self, config, parent=None, language=None):
        super().__init__(parent)
        self.language = language or InterfaceLanguage()
        self.setWindowTitle("Configure CORS")
        self.resize(400, 250)

        icon = get_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        layout = QVBoxLayout(self)
        self.form = QFormLayout()
        self.line_origin = QLineEdit(config.get('origin', '*'))
        self.line_methods = QLineEdit(config.get('methods', 'GET, POST, OPTIONS, PUT, DELETE'))
        self.line_headers = QLineEdit(config.get('headers', 'Content-Type, Authorization'))
        self.form.addRow("Allow Origin:", self.line_origin)
        self.form.addRow("Allow Methods:", self.line_methods)
        self.form.addRow("Allow Headers:", self.line_headers)
        layout.addLayout(self.form)
        
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.language.apply(self.language.capture(self))
        self.buttons.button(QDialogButtonBox.Cancel).setText(self.language.text("Cancel"))

    def get_config(self):
        return {
            'origin': self.line_origin.text(),
            'methods': self.line_methods.text(),
            'headers': self.line_headers.text()
        }


class RedirectionDialog(QDialog):
    """
    Dialog for editing URL redirections.
    """
    def __init__(self, redirections, parent=None, language=None):
        super().__init__(parent)
        self.language = language or InterfaceLanguage()
        self.setWindowTitle("Edit Redirections")
        self.resize(500, 400)

        icon = get_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Path", "Target URL", "Code"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)
        
        for row, (src, dest, code) in enumerate(redirections):
            self.add_row(src, dest, str(code))

        btn_layout = QHBoxLayout()
        btn_add = QPushButton("Add Row", self)
        btn_add.clicked.connect(lambda: self.add_row("/", "http://example.com", "301"))
        btn_remove = QPushButton("Remove Selected", self)
        btn_remove.clicked.connect(self.remove_row)
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_remove)
        layout.addLayout(btn_layout)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.language.apply(self.language.capture(self))
        self.table.setHorizontalHeaderLabels([self.language.text(text) for text in ("Path", "Target URL", "Code")])
        self.buttons.button(QDialogButtonBox.Cancel).setText(self.language.text("Cancel"))

    def add_row(self, src, dest, code):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(src))
        self.table.setItem(row, 1, QTableWidgetItem(dest))
        self.table.setItem(row, 2, QTableWidgetItem(code))

    def remove_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def get_redirections(self):
        redirs = []
        for r in range(self.table.rowCount()):
            try:
                src = self.table.item(r, 0).text()
                dest = self.table.item(r, 1).text()
                code = int(self.table.item(r, 2).text())
                redirs.append((src, dest, code))
            except:
                pass
        return redirs


class ShareFolderDialog(QDialog):
    """
    Dialog for configuring and triggering SMB network sharing.
    """
    def __init__(self, initial_folder=None, parent=None, language=None):
        super().__init__(parent)
        self.language = language or InterfaceLanguage()
        self.setWindowTitle("Share folder on network")
        self.resize(520, 340)

        icon = get_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        layout = QVBoxLayout(self)

        self.help_text = QLabel(
            "Configure network sharing (SMB) for the selected folder. "
            "This sets up network services, firewall rules, and access permissions.",
            self
        )
        self.help_text.setWordWrap(True)
        self.help_text.setStyleSheet("color: #b0b0b0; font-size: 12px; margin-bottom: 8px;")
        layout.addWidget(self.help_text)

        form = QFormLayout()
        form.setSpacing(10)

        # Folder selection row
        folder_row = QHBoxLayout()
        current_folder = initial_folder or os.getcwd()
        if not os.path.isdir(current_folder):
            current_folder = os.getcwd()
        self.line_folder = QLineEdit(current_folder, self)
        self.btn_browse = QPushButton("...", self)
        self.btn_browse.setMaximumWidth(40)
        self.btn_browse.clicked.connect(self.browse_folder)
        folder_row.addWidget(self.line_folder, 1)
        folder_row.addWidget(self.btn_browse)
        form.addRow("Folder path:", folder_row)

        # Share name
        folder_leaf = Path(current_folder).name or "Compartilhado"
        self.line_name = QLineEdit(folder_leaf, self)
        self.line_name.setPlaceholderText("Share name")
        form.addRow("Share name:", self.line_name)

        self.line_folder.textChanged.connect(self._on_folder_changed)

        # User / Group
        self.line_user = QLineEdit("Todos", self)
        self.line_user.setPlaceholderText("Todos (Everyone)")
        form.addRow("User or group:", self.line_user)

        # Access permission
        self.combo_access = QComboBox(self)
        self.combo_access.addItem("Read and write", "Escrita")
        self.combo_access.addItem("Read only", "Leitura")
        form.addRow("Access permission:", self.combo_access)

        # Security: allow access without password
        self.chk_no_password = QCheckBox("Allow access without password (guest access)", self)
        self.chk_no_password.setToolTip(
            "Configures system policies to allow anonymous/guest access without entering credentials."
        )
        form.addRow("", self.chk_no_password)

        layout.addLayout(form)

        # Error label
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #ff9aa7;")
        self.error.hide()
        layout.addWidget(self.error)

        # Buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.button(QDialogButtonBox.Ok).setText("Share on Network")
        self.buttons.button(QDialogButtonBox.Cancel).setText("Cancel")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.ui_translations = self.language.capture(self)
        self.retranslate()

    def retranslate(self):
        self.language.apply(self.ui_translations)
        self.setWindowTitle(self.language.text("Share folder on network"))
        self.buttons.button(QDialogButtonBox.Ok).setText(self.language.text("Share on Network"))
        self.buttons.button(QDialogButtonBox.Cancel).setText(self.language.text("Cancel"))
        self.combo_access.setItemText(0, self.language.text("Read and write"))
        self.combo_access.setItemText(1, self.language.text("Read only"))

    def _on_folder_changed(self, text):
        path = text.strip()
        if path:
            leaf = Path(path).name
            if leaf:
                self.line_name.setText(leaf)

    def browse_folder(self):
        current = self.line_folder.text().strip() or os.getcwd()
        dir_path = QFileDialog.getExistingDirectory(self, self.language.text("Select Directory"), current)
        if dir_path:
            self.line_folder.setText(dir_path)

    def accept(self):
        folder = self.line_folder.text().strip()
        if not folder or not os.path.isdir(folder):
            self.error.setText(self.language.text("Select an existing folder."))
            self.error.show()
            return
        name = self.line_name.text().strip()
        if not name:
            self.error.setText(self.language.text("Enter a valid share name."))
            self.error.show()
            return
        if re.search(r'[\\/:*?"<>|]', name):
            self.error.setText(self.language.text('Share name cannot contain characters: \\ / : * ? " < > |'))
            self.error.show()
            return
        self.error.hide()
        super().accept()

    def get_config(self):
        return {
            'folder': os.path.abspath(self.line_folder.text().strip()),
            'name': self.line_name.text().strip(),
            'user': self.line_user.text().strip() or "Todos",
            'access': self.combo_access.currentData(),
            'without_password': self.chk_no_password.isChecked()
        }


class ActiveSharesDialog(QDialog):
    """
    Dialog that lists active SMB network shares and allows removing them.
    """

    def __init__(self, parent=None, language=None):
        super().__init__(parent)
        from PySide6.QtCore import QTimer as _QTimer
        self._QTimer = _QTimer
        self.language = language or InterfaceLanguage()
        self.setWindowTitle(self.language.text("Active Network Shares"))
        self.resize(1000, 480)

        icon = get_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        layout = QVBoxLayout(self)

        # Description
        self.help_label = QLabel(
            self.language.text(
                "Network shares currently active on this machine (SMB/Windows). "
                "System shares (C$, ADMIN$, IPC$) are hidden."
            ),
            self,
        )
        self.help_label.setWordWrap(True)
        self.help_label.setStyleSheet("color: #b0b0b0; font-size: 12px; margin-bottom: 6px;")
        layout.addWidget(self.help_label)

        # Table
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels([
            self.language.text("Share name"),
            self.language.text("Local path"),
            self.language.text("Description"),
            self.language.text("Access addresses"),
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(100)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setWordWrap(True)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # Status label
        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #ff9aa7; font-size: 11px;")
        self.status_label.hide()
        layout.addWidget(self.status_label)

        # Buttons row
        btn_row = QHBoxLayout()
        self.btn_refresh = QPushButton(self.language.text("Refresh"), self)
        self.btn_refresh.clicked.connect(self.refresh_shares)
        self.btn_remove = QPushButton(self.language.text("Remove Share"), self)
        self.btn_remove.setEnabled(False)
        self.btn_remove.clicked.connect(self.remove_selected)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_remove)
        layout.addLayout(btn_row)

        # Close button
        self.buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        self.buttons.button(QDialogButtonBox.Close).setText(self.language.text("Close"))
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.table.selectionModel().selectionChanged.connect(self._update_remove_btn)

        self.refresh_shares()

    def refresh_shares(self):
        from ..core.windows_share import list_smb_shares
        self.btn_refresh.setEnabled(False)
        self.status_label.hide()
        self.table.setRowCount(0)

        ok, result = list_smb_shares()
        if not ok:
            self.status_label.setText(self.language.text(str(result)))
            self.status_label.show()
            self.btn_refresh.setEnabled(True)
            return

        shares = result  # list[dict]
        if not shares:
            self.status_label.setText(self.language.text("No active shares found."))
            self.status_label.setStyleSheet("color: #b0b0b0; font-size: 11px;")
            self.status_label.show()
        else:
            self.status_label.hide()
            self.status_label.setStyleSheet("color: #ff9aa7; font-size: 11px;")

        for share in shares:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(share["name"]))
            self.table.setItem(row, 1, QTableWidgetItem(share["path"]))
            self.table.setItem(row, 2, QTableWidgetItem(share["description"]))
            addresses = self._access_addresses(share["name"])
            address_item = QTableWidgetItem(addresses)
            address_item.setToolTip(addresses)
            self.table.setItem(row, 3, address_item)
            for column in range(4):
                item = self.table.item(row, column)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                item.setToolTip(item.text())

        self._update_remove_btn()
        self.btn_refresh.setEnabled(True)

    @staticmethod
    def _access_addresses(share_name):
        import socket
        import psutil
        hosts = []
        try:
            for addresses in psutil.net_if_addrs().values():
                for addr in addresses:
                    if addr.family == socket.AF_INET and not addr.address.startswith(("127.", "169.254.")):
                        hosts.append(addr.address)
        except OSError:
            pass
        return "\n".join(f"\\\\{h}\\{share_name}" for h in dict.fromkeys(hosts))

    def _update_remove_btn(self):
        self.btn_remove.setEnabled(self.table.currentRow() >= 0 and self.table.rowCount() > 0)

    def remove_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        name_item = self.table.item(row, 0)
        if not name_item:
            return
        share_name = name_item.text()

        confirm = QMessageBox.question(
            self,
            self.language.text("Remove Share"),
            self.language.text(
                "Remove the share '{name}'? This will revoke network access to it.",
                name=share_name,
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        from ..core.windows_share import remove_smb_share
        ok, msg = remove_smb_share(share_name)
        if ok:
            # Give the OS a moment to apply the change, then refresh
            self._QTimer.singleShot(1800, self.refresh_shares)
        else:
            if "canceled" not in msg.lower() and "cancelado" not in msg.lower():
                self.status_label.setText(
                    self.language.text("Unable to remove share: {error}", error=msg)
                )
                self.status_label.setStyleSheet("color: #ff9aa7; font-size: 11px;")
                self.status_label.show()


class PrinterSharingDialog(QDialog):
    """
    Dialog that lists installed printers and lets the user share/unshare them
    over the local network (SMB).
    """

    def __init__(self, parent=None, language=None):
        super().__init__(parent)
        from PySide6.QtCore import QTimer as _QTimer
        self._QTimer = _QTimer
        self.language = language or InterfaceLanguage()
        self._printers = []

        self.setWindowTitle(self.language.text("Printer Sharing"))
        self.resize(660, 420)

        icon = get_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        layout = QVBoxLayout(self)

        desc = QLabel(
            self.language.text(
                "Share or stop sharing printers connected to this computer over "
                "the local network (SMB). Administrator privileges may be required."
            ),
            self,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #b0b0b0; font-size: 12px; margin-bottom: 4px;")
        layout.addWidget(desc)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels([
            self.language.text("Printer"),
            self.language.text("Share name"),
            self.language.text("Status"),
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        name_row = QHBoxLayout()
        self.lbl_share_name = QLabel(self.language.text("Share name:"), self)
        self.line_share_name = QLineEdit(self)
        self.line_share_name.setPlaceholderText(self.language.text("Network share name"))
        self.line_share_name.setMaximumWidth(220)
        name_row.addWidget(self.lbl_share_name)
        name_row.addWidget(self.line_share_name)
        name_row.addStretch()
        layout.addLayout(name_row)

        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #ff9aa7; font-size: 11px;")
        self.status_label.hide()
        layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.btn_refresh = QPushButton(self.language.text("Refresh"), self)
        self.btn_refresh.clicked.connect(self.refresh_printers)
        self.btn_share = QPushButton(self.language.text("Share Printer"), self)
        self.btn_share.setEnabled(False)
        self.btn_share.clicked.connect(self.share_selected)
        self.btn_unshare = QPushButton(self.language.text("Stop Sharing"), self)
        self.btn_unshare.setEnabled(False)
        self.btn_unshare.clicked.connect(self.unshare_selected)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_share)
        btn_row.addWidget(self.btn_unshare)
        layout.addLayout(btn_row)

        self.close_buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        self.close_buttons.rejected.connect(self.reject)
        layout.addWidget(self.close_buttons)

        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.refresh_printers()

    def refresh_printers(self):
        from ..core.windows_share import list_printers
        self.btn_refresh.setEnabled(False)
        self.status_label.hide()
        self.table.setRowCount(0)
        self._printers = []
        self._update_buttons()

        ok, result = list_printers()
        if not ok:
            self._show_error(self.language.text(str(result)))
            self.btn_refresh.setEnabled(True)
            return

        self._printers = result
        if not self._printers:
            self.status_label.setText(self.language.text("No printers found on this machine."))
            self.status_label.setStyleSheet("color: #b0b0b0; font-size: 11px;")
            self.status_label.show()

        from PySide6.QtGui import QColor
        for printer in self._printers:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(printer["name"]))
            self.table.setItem(row, 1, QTableWidgetItem(printer["share_name"]))
            if printer["shared"]:
                status_item = QTableWidgetItem(self.language.text("Shared \u2713"))
                status_item.setForeground(QColor("#2ecc71"))
            else:
                status_item = QTableWidgetItem(self.language.text("Not shared"))
                status_item.setForeground(QColor("#b0b0b0"))
            self.table.setItem(row, 2, status_item)

        self._update_buttons()
        self.btn_refresh.setEnabled(True)

    def _on_selection_changed(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._printers):
            printer = self._printers[row]
            default_name = printer["share_name"] or printer["name"][:20]
            self.line_share_name.setText(default_name)
        self._update_buttons()

    def _update_buttons(self):
        row = self.table.currentRow()
        has_sel = 0 <= row < len(self._printers)
        shared = self._printers[row]["shared"] if has_sel else False
        self.btn_share.setEnabled(has_sel and not shared)
        self.btn_unshare.setEnabled(has_sel and shared)
        self.line_share_name.setEnabled(has_sel and not shared)

    def _show_error(self, msg):
        self.status_label.setText(msg)
        self.status_label.setStyleSheet("color: #ff9aa7; font-size: 11px;")
        self.status_label.show()

    def _schedule_refresh(self):
        self._QTimer.singleShot(2000, self.refresh_printers)

    def share_selected(self):
        import re as _re
        row = self.table.currentRow()
        if row < 0 or row >= len(self._printers):
            return
        printer = self._printers[row]
        share_name = self.line_share_name.text().strip()
        if not share_name:
            self._show_error(self.language.text("Enter a valid share name for the printer."))
            return
        if _re.search(r'[\\/:*?"<>|]', share_name):
            self._show_error(self.language.text('Share name cannot contain characters: \\ / : * ? " < > |'))
            return
        from ..core.windows_share import share_printer
        self.status_label.hide()
        ok, msg = share_printer(printer["name"], share_name)
        if ok:
            self._schedule_refresh()
        else:
            if "canceled" not in msg.lower() and "cancelado" not in msg.lower():
                self._show_error(self.language.text("Unable to share printer: {error}", error=msg))

    def unshare_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._printers):
            return
        printer = self._printers[row]
        confirm = QMessageBox.question(
            self,
            self.language.text("Stop Sharing"),
            self.language.text(
                "Stop sharing the printer '{name}'? Network users will lose access.",
                name=printer["name"],
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        from ..core.windows_share import unshare_printer
        self.status_label.hide()
        ok, msg = unshare_printer(printer["name"])
        if ok:
            self._schedule_refresh()
        else:
            if "canceled" not in msg.lower() and "cancelado" not in msg.lower():
                self._show_error(self.language.text("Unable to stop sharing printer: {error}", error=msg))

