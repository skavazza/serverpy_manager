"""Desktop file-transfer progress, independently of general HTTP activity."""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QPushButton, QStyle,
)

from .activity import format_bytes


class TransfersPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.session = None
        self.items = {}
        layout = QVBoxLayout(self)
        note = QLabel('HTTP file transfers for this server session. Progress counts file content only. Download completion means bytes sent by the server, not a confirmed save on the client. Recent history keeps 100 transfers.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 9, self)
        self.table.setObjectName('file_transfers')
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setMinimumHeight(250)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        self.cancel_button = QPushButton(self.style().standardIcon(QStyle.SP_BrowserStop), 'Cancel selected transfer', self)
        self.cancel_button.setMinimumHeight(44)
        self.cancel_button.clicked.connect(self.cancel_selected)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        layout.insertLayout(2, actions)
        self.table.itemSelectionChanged.connect(self.update_actions)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.labels = controller.language.capture(self)
        self.retranslate()

    def selected_id(self):
        if self.table.selectionModel().hasSelection():
            cell = self.table.item(self.table.currentRow(), 0)
            return cell.data(Qt.UserRole) if cell else None
        return None

    def update_actions(self):
        item = self.items.get(self.selected_id())
        self.cancel_button.setEnabled(bool(item and item['state'] == 'In progress' and
                                          self.session is self.controller.server_manager.transfers))

    def cancel_selected(self):
        if self.session is self.controller.server_manager.transfers:
            token = self.selected_id()
            if token is not None:
                self.session.cancel(token)
                self.refresh()

    def refresh(self):
        language = self.controller.language
        session = self.controller.server_manager.transfers
        selected = self.selected_id() if self.session is session else None
        self.session = session
        data = session.snapshot()
        self.items = {item['id']: item for item in data}
        self.table.setRowCount(len(data))
        for row, item in enumerate(data):
            progress = item['done'] / item['size'] * 100 if item['size'] else 100 if item['state'] == 'Completed' else 0
            remaining = f"{item['remaining']:.0f} s" if item['remaining'] is not None else '—'
            values = (language.text(item['direction']), item['path'], item['ip'],
                language.text(item['state']), f'{progress:.0f}%',
                f"{format_bytes(item['done'])} / {format_bytes(item['size'])}",
                format_bytes(item['rate']) + '/s', remaining, f"{item['elapsed']:.1f} s")
            for column, value in enumerate(values):
                cell = self.table.item(row, column)
                if cell is None:
                    cell = QTableWidgetItem()
                    self.table.setItem(row, column, cell)
                cell.setText(value)
                cell.setToolTip(value)
                cell.setData(Qt.UserRole, item['id'])
            if item['id'] == selected:
                self.table.selectRow(row)
        self.summary.setText(language.text('Active transfers: {active} | Recent transfers: {recent}',
            active=sum(item['active'] for item in data), recent=sum(not item['active'] for item in data)))
        self.update_actions()

    def retranslate(self):
        language = self.controller.language
        language.apply(self.labels)
        self.table.setHorizontalHeaderLabels([language.text(s) for s in
            ('Direction', 'File', 'IP address', 'Status', 'Progress', 'Transferred', 'Speed', 'Time remaining', 'Duration')])
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)
