"""Desktop-only view of this server's HTTP connections and recent requests."""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QCheckBox, QSplitter,
)


def format_bytes(value):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024


class ActivityPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel('Activity for this HTTP server only. SMB sessions are not included. Counters reset when the server starts; recent clients remain visible for 5 minutes.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.summary = QLabel(self)
        self.summary.setObjectName('http_activity_summary')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.totals = QLabel(self)
        self.totals.setWordWrap(True)
        self.totals.setToolTip('Counts include HTTP headers and bytes read or written by the application, without TLS or TCP overhead. Rates use a rolling window of about 5 seconds.')
        layout.addWidget(self.totals)
        self.state = QLabel(self)
        layout.addWidget(self.state)
        splitter = QSplitter(Qt.Vertical, self)
        clients = QWidget(splitter)
        client_layout = QVBoxLayout(clients)
        client_layout.setContentsMargins(0, 0, 0, 0)
        client_layout.addWidget(QLabel('Recent HTTP clients', clients))
        self.clients = self.make_table(clients, 0)
        self.clients.setObjectName('http_clients')
        client_layout.addWidget(self.clients)
        requests = QWidget(splitter)
        request_layout = QVBoxLayout(requests)
        request_layout.setContentsMargins(0, 0, 0, 0)
        self.hide_background = QCheckBox('Hide background requests in the request list', requests)
        self.hide_background.setChecked(True)
        request_layout.addWidget(self.hide_background)
        request_layout.addWidget(QLabel('Active and recent HTTP requests', requests))
        self.requests = self.make_table(requests, 2)
        self.requests.setObjectName('http_requests')
        request_layout.addWidget(self.requests)
        splitter.addWidget(clients)
        splitter.addWidget(requests)
        layout.addWidget(splitter)
        self.hide_background.toggled.connect(self.refresh)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.labels = controller.language.capture(self)
        self.retranslate()

    @staticmethod
    def make_table(parent, stretch_column):
        table = QTableWidget(parent)
        table.setColumnCount(7)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(stretch_column, QHeaderView.Stretch)
        table.setMinimumHeight(120)
        return table

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    @staticmethod
    def fill(table, rows):
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                cell = table.item(row, column)
                if cell is None:
                    cell = QTableWidgetItem()
                    table.setItem(row, column, cell)
                cell.setText(str(value))
                cell.setToolTip(str(value))

    def refresh(self):
        language = self.controller.language
        data = self.controller.server_manager.traffic.snapshot()
        self.summary.setText(language.text(
            'Open connections: {connections} | Active requests: {active} | Active clients: {clients} | Requests: {requests} | Failures: {errors}',
            connections=data['connections'], active=data['active_requests'], clients=data['active_clients'],
            requests=data['requests'], errors=data['errors'],
        ))
        self.totals.setText(language.text(
            'Received: {received} | Sent: {sent} | Incoming: {incoming}/s | Outgoing: {outgoing}/s',
            received=format_bytes(data['received']), sent=format_bytes(data['sent']),
            incoming=format_bytes(data['receive_rate']), outgoing=format_bytes(data['send_rate']),
        ))
        self.state.setText(language.text('HTTP server running' if self.controller.server_manager.is_running else 'HTTP server stopped. Activity remains visible until the next start.'))
        self.fill(self.clients, [(
            item['ip'], item['connections'], item['active_requests'], item['requests'],
            format_bytes(item['received']), format_bytes(item['sent']), f"{item['last_seen']:.0f} s",
        ) for item in data['clients']])
        rows = []
        for item in data['activity']:
            if self.hide_background.isChecked() and (item['path'].endswith('/api/ping') or item['path'].startswith('/_serverpy/pwa/')):
                continue
            if item['active']:
                state = 'In progress'
            elif item['interrupted']:
                state = 'Interrupted'
            elif item['status'] >= 400:
                state = 'HTTP error'
            else:
                state = 'Completed'
            status = language.text(state) + (f" ({item['status']})" if item['status'] is not None else '')
            rows.append((item['ip'], item['method'], item['path'], status,
                         format_bytes(item['received']), format_bytes(item['sent']), f"{item['elapsed']:.1f} s"))
        self.fill(self.requests, rows)

    def retranslate(self):
        language = self.controller.language
        language.apply(self.labels)
        self.clients.setHorizontalHeaderLabels([language.text(s) for s in
            ('IP address', 'Open', 'Active requests', 'Requests', 'Received', 'Sent', 'Last activity')])
        self.requests.setHorizontalHeaderLabels([language.text(s) for s in
            ('IP address', 'Method', 'Path', 'Status', 'Received', 'Sent', 'Duration')])
        self.refresh()
