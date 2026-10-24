"""Desktop WIA scanning with asynchronous discovery and acquisition."""

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QPushButton, QFileDialog, QStyle,
)

from ..core import scanning


class _Signals(QObject):
    finished = Signal(bool, object)


class _Task(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = _Signals()

    def run(self):
        try:
            ok, result = self.operation()
        except Exception as error:
            ok, result = False, str(error)
        self.signals.finished.emit(ok, result)


class ScannerPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.running = False
        self.last_file = None
        self.status_source = 'Refresh to find available scanners.'
        self.detail = ''
        layout = QVBoxLayout(self)
        self.note = QLabel(self)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        row = QHBoxLayout()
        self.devices = QComboBox(self)
        self.devices.setMinimumContentsLength(15)
        self.devices.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.devices, 1)
        self.refresh_button = QPushButton(self)
        self.refresh_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        self.output_label = QLabel(self)
        layout.addWidget(self.output_label)
        self.output = QLineEdit(self)
        self.output.setReadOnly(True)
        self.output_label.setBuddy(self.output)
        layout.addWidget(self.output)
        row = QHBoxLayout()
        self.browse_button = QPushButton(self)
        self.browse_button.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.server_folder_button = QPushButton(self)
        self.server_folder_button.setIcon(self.style().standardIcon(QStyle.SP_DirLinkIcon))
        row.addWidget(self.browse_button)
        row.addWidget(self.server_folder_button)
        layout.addLayout(row)
        self.scan_button = QPushButton(self)
        self.scan_button.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        layout.addWidget(self.scan_button)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.open_button = QPushButton(self)
        self.open_button.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        layout.addWidget(self.open_button)
        self.refresh_button.clicked.connect(self.refresh)
        self.browse_button.clicked.connect(self.choose_folder)
        self.server_folder_button.clicked.connect(self.use_server_folder)
        self.scan_button.clicked.connect(self.scan)
        self.open_button.clicked.connect(self.open_output)
        self.devices.currentIndexChanged.connect(self.update_actions)
        self.output.textChanged.connect(self.update_actions)
        self.retranslate()

    def update_actions(self):
        ready = self.controller.windows_share_supported and not self.running
        for widget in (self.devices, self.refresh_button, self.browse_button, self.server_folder_button):
            widget.setEnabled(ready)
        self.scan_button.setEnabled(ready and bool(self.devices.currentData()) and Path(self.output.text()).is_dir() and bool(self.output.text()))
        self.open_button.setEnabled(not self.running and self.last_file is not None)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.controller.language.text('Choose scan output folder'), self.output.text())
        if folder:
            self.output.setText(folder)

    def use_server_folder(self):
        manager = self.controller.server_manager
        folder = manager.httpd.directory if manager.is_running and manager.httpd else self.controller.window.line_root_folder.text().strip()
        self.output.setText(str(folder))

    def start(self, operation, callback, source):
        if self.running or not self.controller.windows_share_supported:
            return
        self.running = True
        self.status_source = source
        self.detail = ''
        self.retranslate()
        self.task = _Task(operation)
        self.task.signals.finished.connect(callback)
        QThreadPool.globalInstance().start(self.task)

    def refresh(self):
        self.start(scanning.list_scanners, self.discovered, 'Looking for scanners...')

    def discovered(self, ok, result):
        previous = self.devices.currentData()
        self.running = False
        self.devices.clear()
        if ok:
            for device in result:
                self.devices.addItem(device['name'], device['id'])
            index = self.devices.findData(previous)
            if index >= 0:
                self.devices.setCurrentIndex(index)
            self.status_source = 'Select a scanner and an output folder.' if result else 'No WIA scanners found. Connect the device and install its WIA driver, then refresh.'
            self.detail = ''
        else:
            self.status_source = 'Unable to list scanners.'
            self.detail = str(result)
        self.retranslate()

    def scan(self):
        if self.running or not self.devices.currentData() or not self.output.text():
            return
        device_id, directory = self.devices.currentData(), self.output.text()
        self.start(lambda: scanning.scan_page(device_id, directory), self.scanned,
                   'Scanning one page... Wait for the device to finish (up to 2 minutes).')

    def scanned(self, ok, result):
        self.running = False
        self.status_source = 'Scan saved. Refresh the web explorer to see the file if this folder is shared.' if ok else 'Unable to scan the page.'
        self.detail = str(result)
        if ok:
            self.last_file = Path(result)
        self.retranslate()

    def open_output(self):
        if self.last_file and not self.running:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_file.parent))):
                self.status_source = 'Unable to open the output folder.'
                self.retranslate()

    def retranslate(self):
        text = self.controller.language.text
        self.note.setText(text('Scan one page to PNG using the scanner driver defaults. Place the page in the default source before starting. Files saved in a shared folder are accessible to its authorized clients. Scanning starts only from this desktop.'))
        self.devices.setAccessibleName(text('Scanner'))
        self.output_label.setText(text('Scan output folder:'))
        self.output.setAccessibleName(text('Scan output folder:'))
        for widget, source in (
            (self.refresh_button, 'Refresh scanners'), (self.browse_button, 'Choose output folder'),
            (self.server_folder_button, 'Use server folder'), (self.scan_button, 'Scan one page'),
            (self.open_button, 'Open saved scan folder'),
        ):
            widget.setText(text(source))
        source = self.status_source if self.controller.windows_share_supported else 'Scanning requires Windows 10 or 11 and a WIA driver.'
        self.status.setText(text(source) + ('\n' + text(self.detail) if self.detail else ''))
        self.update_actions()
