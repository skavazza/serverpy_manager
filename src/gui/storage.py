"""Storage tab: discover drives without blocking the GUI and share their files."""

import os
import sys

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)

from ..core.storage import list_external_drives
# Preserve the previous public import path for existing integrations.
from .android_panel import AndroidDevicePanel


class _ScanSignals(QObject):
    finished = Signal(bool, object)
    progress = Signal(int, int)


class _DriveScan(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = _ScanSignals()

    def run(self):
        try:
            ok, result = list_external_drives()
        except Exception as error:
            ok, result = False, str(error)
        self.signals.finished.emit(ok, result)


class StoragePanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.drives = []
        self.loading = False
        self.loaded = False
        self.status_source = 'Connect a USB drive or external hard drive, then click Refresh.'
        self.error_detail = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.description = QLabel(
            'Share files from USB drives and external hard drives. The computer must stay on and the drive must remain connected.', self,
        )
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.table = QTableWidget(0, 4, self)
        self.table.setObjectName('external_drives')
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setMinimumHeight(180)
        layout.addWidget(self.table)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.refresh_button = QPushButton('Refresh', self)
        self.share_button = QPushButton('Share files on Windows network', self)
        self.http_button = QPushButton('Use in HTTP server', self)
        row.addWidget(self.refresh_button)
        row.addStretch()
        layout.addLayout(row)
        # Separate rows fit the minimum window width in either language.
        layout.addWidget(self.share_button)
        layout.addWidget(self.http_button)
        self.note = QLabel('These actions share files. Printers are managed in the Printers tab; full USB redirection is not available.', self)
        self.note.setWordWrap(True)
        self.note.setStyleSheet('color: #b8c1cc;')
        layout.addWidget(self.note)
        self.refresh_button.clicked.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self.update_actions)
        self.share_button.clicked.connect(self.share_selected)
        self.http_button.clicked.connect(self.use_in_http)
        self.labels = controller.language.capture(self)
        self.retranslate()

    def selected_drive(self):
        row = self.table.currentRow()
        if self.table.selectionModel().hasSelection() and 0 <= row < len(self.drives):
            return self.drives[row]
        return None

    def update_actions(self):
        supports_file_sharing = self.controller.windows_share_supported or sys.platform.startswith('linux')
        selected = self.selected_drive() is not None and not self.loading
        self.share_button.setEnabled(selected and supports_file_sharing)
        self.http_button.setEnabled(selected and not self.controller.server_manager.is_running)
        self.refresh_button.setEnabled(not self.loading and supports_file_sharing)
        self.http_button.setToolTip(self.controller.language.text('Stop the HTTP server before changing its folder.') if self.controller.server_manager.is_running else '')

    def refresh(self):
        supports_file_sharing = self.controller.windows_share_supported or sys.platform.startswith('linux')
        if self.loading or not supports_file_sharing:
            return
        self.loaded = True
        self.loading = True
        self.previous_path = (self.selected_drive() or {}).get('path')
        self.drives = []
        self.table.setRowCount(0)
        self.status_source = 'Looking for external drives...'
        self.error_detail = ''
        self.retranslate()
        self.scan = _DriveScan()
        self.scan.signals.finished.connect(self.scan_finished)
        QThreadPool.globalInstance().start(self.scan)

    def scan_finished(self, ok, result):
        self.loading = False
        self.drives = result if ok else []
        self.table.setRowCount(0)
        if not ok:
            self.status_source = 'Unable to query external drives.'
            self.error_detail = str(result)
        else:
            self.error_detail = ''
            self.status_source = 'Select a drive to share its files.' if self.drives else 'No USB drives or external hard drives found. Connect a drive and click Refresh.'
            for row, drive in enumerate(self.drives):
                self.table.insertRow(row)
                for column, value in enumerate((drive['path'], drive['label'], self.format_size(drive['size']), self.format_size(drive['free']))):
                    self.table.setItem(row, column, QTableWidgetItem(value))
                if drive['path'] == getattr(self, 'previous_path', None):
                    self.table.selectRow(row)
        self.retranslate()

    @staticmethod
    def format_size(size):
        return f'{size / (1024 ** 3):.1f} GiB'

    def checked_path(self):
        drive = self.selected_drive()
        if not drive:
            return None
        if not os.path.isdir(drive['path']):
            self.status_source = 'The drive is no longer available. Reconnect it and click Refresh.'
            self.error_detail = ''
            self.drives = []
            self.table.setRowCount(0)
            self.retranslate()
            return None
        return drive['path']

    def share_selected(self):
        path = self.checked_path()
        if path:
            self.controller.share_folder(path)

    def use_in_http(self):
        if self.controller.server_manager.is_running:
            return
        path = self.checked_path()
        if path:
            self.controller.window.line_root_folder.setText(path)
            self.controller.save_server_preferences()
            self.controller.navigation.tabs.setCurrentIndex(0)

    def retranslate(self):
        language = self.controller.language
        language.apply(self.labels)
        self.table.setHorizontalHeaderLabels([language.text(s) for s in ('Drive', 'Volume name', 'Capacity', 'Free space')])
        supported = self.controller.windows_share_supported or sys.platform.startswith('linux')
        source = self.status_source if supported else 'Drive discovery requires Windows 10 or 11.'
        text = language.text(source)
        if self.error_detail and self.error_detail != source:
            text += '\n' + language.text(self.error_detail)
        self.status.setText(text)
        self.update_actions()
