"""Asynchronous print queue panel."""

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QMessageBox, QStyle,
)

from ..core import printing, windows_share


class _Signals(QObject):
    finished = Signal(object)


class _Task(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = _Signals()

    def run(self):
        try:
            result = self.operation()
        except Exception as error:
            result = False, str(error)
        self.signals.finished.emit(result)


class PrintQueuePanel(QWidget):
    HEADERS = ('ID', 'Document', 'Owner', 'Status', 'Pages printed', 'Total pages', 'Submitted')
    KEYS = ('ID', 'DocumentName', 'UserName', 'JobStatus', 'PagesPrinted', 'TotalPages', 'Submitted')

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.supported = controller.windows_share_supported
        self.running = False
        self.jobs = []
        self.status_source = 'Refresh to load installed printers.' if self.supported else 'Print queue requires Windows 10 or 11.'
        layout = QVBoxLayout(self)
        self.note = QLabel(self)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        row = QHBoxLayout()
        self.printers = QComboBox(self)
        row.addWidget(self.printers, 1)
        self.refresh_button = QPushButton(self)
        self.refresh_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        row.addWidget(self.refresh_button)
        self.cancel_button = QPushButton(self)
        self.cancel_button.setIcon(self.style().standardIcon(QStyle.SP_DialogCancelButton))
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.table = QTableWidget(0, len(self.KEYS), self)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        layout.addWidget(self.table)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.refresh_button.clicked.connect(self.refresh)
        self.printers.currentIndexChanged.connect(self.load_jobs)
        self.table.itemSelectionChanged.connect(self.update_actions)
        self.cancel_button.clicked.connect(self.cancel_selected)
        self.retranslate()

    def update_actions(self):
        ready = self.supported and not self.running
        self.refresh_button.setEnabled(ready)
        self.printers.setEnabled(ready)
        self.cancel_button.setEnabled(ready and 0 <= self.table.currentRow() < len(self.jobs))

    def start(self, operation, callback):
        if self.running or not self.supported:
            return
        self.running = True
        self.status_source = 'Checking print queue...'
        self.retranslate()
        self.task = _Task(operation)
        self.task.signals.finished.connect(callback)
        QThreadPool.globalInstance().start(self.task)

    def refresh(self):
        self.start(windows_share.list_printers, self.printers_loaded)

    def printers_loaded(self, result):
        self.running = False
        ok, data = result
        previous = self.printers.currentText()
        self.printers.blockSignals(True)
        self.printers.clear()
        if ok:
            self.printers.addItems([printer['name'] for printer in data])
            index = self.printers.findText(previous)
            if index >= 0:
                self.printers.setCurrentIndex(index)
        self.printers.blockSignals(False)
        if ok and self.printers.count():
            self.load_jobs()
        else:
            self.jobs_loaded((ok, [] if ok else data))

    def load_jobs(self):
        if self.running:
            return
        self.jobs = []
        self.table.setRowCount(0)
        printer = self.printers.currentText()
        if printer:
            self.start(lambda: printing.list_print_jobs(printer), self.jobs_loaded)
        else:
            self.update_actions()

    def jobs_loaded(self, result):
        self.running = False
        ok, data = result
        self.jobs = data if ok else []
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.jobs))
        for row, job in enumerate(self.jobs):
            for column, key in enumerate(self.KEYS):
                value = job.get(key)
                self.table.setItem(row, column, QTableWidgetItem('' if value is None else str(value)))
        self.status_source = 'Print queue updated.' if ok and self.jobs else 'No queued print jobs.' if ok else data
        self.retranslate()

    def cancel_selected(self):
        row = self.table.currentRow()
        if self.running or not 0 <= row < len(self.jobs):
            return
        job = dict(self.jobs[row])
        language = self.controller.language
        message = language.text('Cancel print job {id}: {document}?').format(id=job['ID'], document=job.get('DocumentName', ''))
        if QMessageBox.question(self, language.text('Print queue'), message,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.start(lambda: printing.cancel_print_job(job), self.cancelled)

    def cancelled(self, result):
        self.running = False
        ok, message = result
        # Invalidate the snapshot even on timeout: the spooler may have acted.
        self.jobs = []
        self.table.setRowCount(0)
        self.status_source = message
        self.retranslate()
        if ok:
            self.load_jobs()

    def retranslate(self):
        text = self.controller.language.text
        self.note.setText(text('Manage queued documents for installed printers. Cancellation uses your current system permissions. Refresh after printing from another application.'))
        self.printers.setAccessibleName(text('Printer'))
        self.refresh_button.setText(text('Refresh printers'))
        self.cancel_button.setText(text('Cancel selected print job'))
        self.table.setHorizontalHeaderLabels([text(value) for value in self.HEADERS])
        self.status.setText(text(self.status_source))
        self.update_actions()
