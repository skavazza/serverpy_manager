"""Local QR code generation and asynchronous network diagnostics."""

from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt
from PySide6.QtGui import QImage, QPainter, QColor, QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QDialogButtonBox,
    QMessageBox,
    QSpinBox,
    QCheckBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)

from ..core.diagnostics import diagnose_endpoint
from .dialogs import get_app_icon
# Preserve the previous public import paths for existing integrations.
from .ssh_panel import SSHPanel, SFTPBrowserDialog


def qr_image(url):
    import qrcode
    code = qrcode.QRCode(border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(url)
    code.make(fit=True)
    matrix = code.get_matrix()
    scale = max(4, 320 // len(matrix))
    image = QImage(len(matrix) * scale, len(matrix) * scale, QImage.Format_RGB32)
    image.fill(QColor('white'))
    painter = QPainter(image)
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                painter.fillRect(x * scale, y * scale, scale, scale, QColor('black'))
    painter.end()
    return image


class QRCodeDialog(QDialog):
    def __init__(self, url, parent, language, temporary=False):
        super().__init__(parent)
        self.language = language
        self.url = url
        self.setWindowTitle(language.text('Access by QR Code'))
        self.setWindowIcon(get_app_icon())
        layout = QVBoxLayout(self)
        self.image = qr_image(url)
        preview = QLabel(self)
        preview.setPixmap(QPixmap.fromImage(self.image))
        preview.setAlignment(Qt.AlignCenter)
        layout.addWidget(preview)
        address = QLineEdit(url, self)
        address.setReadOnly(True)
        layout.addWidget(address)
        host = urlsplit(url).hostname
        note = 'This address works only on this computer. Select a LAN address to connect your phone.' if host in ('localhost', '127.0.0.1', '::1') else 'Connect your phone to the same network. Authentication is still required when enabled.'
        if temporary:
            note = language.text('This QR Code grants access only to the linked file. The link password is required when configured.') + '\n' + language.text(
                'This address works only on this computer. Select a LAN address to connect your phone.' if host in ('localhost', '127.0.0.1', '::1') else 'Connect your phone to the same network.')
        label = QLabel(language.text(note), self)
        label.setWordWrap(True)
        layout.addWidget(label)
        save = QPushButton(language.text('Save QR Code'), self)
        save.clicked.connect(self.save)
        layout.addWidget(save)
        close = QDialogButtonBox(QDialogButtonBox.Close, self)
        close.button(QDialogButtonBox.Close).setText(language.text('Close'))
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def save(self):
        path, _ = QFileDialog.getSaveFileName(self, self.language.text('Save QR Code'), 'serverpy-qr.png', 'PNG (*.png)')
        if path:
            if not path.lower().endswith('.png'):
                path += '.png'
            if not self.image.save(path, 'PNG'):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, self.windowTitle(), self.language.text('Unable to save QR Code.'))


class _Signals(QObject):
    finished = Signal(object)
    progress = Signal(int, int)


class _DiagnosticTask(QRunnable):
    def __init__(self, host, port, tls):
        super().__init__()
        self.arguments = host, port, tls
        self.signals = _Signals()

    def run(self):
        try:
            result = diagnose_endpoint(*self.arguments)
        except Exception as error:
            result = [('Diagnostics', 'Failed', str(error))]
        self.signals.finished.emit(result)


class NetworkPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.rows = []
        self.running = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel('Test a hostname or IP address and a single port. For Cloudflare Tunnel, test the local origin over HTTP if it has no TLS, and the public hostname over HTTPS. Results describe access from this computer; they do not prove access from other devices or identify firewall rules.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.host = QLineEdit('localhost', self)
        self.port = QSpinBox(self)
        self.port.setRange(1, 65535)
        self.port.setValue(8080)
        form.addRow('Host or IP:', self.host)
        form.addRow('Port:', self.port)
        self.tls = QCheckBox('Use HTTPS', self)
        form.addRow(self.tls)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.server_button = QPushButton('Use server address', self)
        self.phone_qr_button = QPushButton('Show phone QR Code', self)
        self.run_button = QPushButton('Run diagnostics', self)
        row.addWidget(self.server_button)
        row.addWidget(self.phone_qr_button)
        row.addWidget(self.run_button)
        layout.addLayout(row)
        self.table = QTableWidget(0, 3, self)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.status_source = ''
        self.server_button.clicked.connect(self.use_server)
        self.phone_qr_button.clicked.connect(self.show_phone_qr)
        self.run_button.clicked.connect(self.run_checks)
        self.controller.access_combo.currentIndexChanged.connect(self.update_qr_action)
        self.labels = controller.language.capture(self)
        self.retranslate()
        self.update_qr_action()

    def update_qr_action(self, _index=None):
        self.phone_qr_button.setEnabled(
            self.controller.server_manager.is_running
            and bool(self.controller.access_combo.currentData())
        )

    def show_phone_qr(self):
        url = self.controller.access_combo.currentData()
        if url and self.controller.server_manager.is_running:
            self.controller.show_qr_code(url)

    def use_server(self):
        url = self.controller.access_combo.currentData()
        if url:
            parsed = urlsplit(url)
            self.host.setText(parsed.hostname or 'localhost')
            self.port.setValue(parsed.port or (443 if parsed.scheme == 'https' else 80))
            self.tls.setChecked(parsed.scheme == 'https')

    def run_checks(self):
        if self.running:
            return
        host = self.host.text().strip()
        if not host or len(host) > 253 or any(c.isspace() or c in '/\\@?#' for c in host):
            self.status_source = 'Enter a hostname or IP address without a URL or port.'
            self.retranslate()
            return
        self.running = True
        self.rows = []
        self.status_source = 'Checking network...'
        self.retranslate()
        for widget in (
            self.host, self.port, self.tls, self.server_button,
            self.phone_qr_button, self.run_button,
        ):
            widget.setEnabled(False)
        self.task = _DiagnosticTask(host, self.port.value(), self.tls.isChecked())
        self.task.signals.finished.connect(self.finished)
        QThreadPool.globalInstance().start(self.task)

    def finished(self, rows):
        self.rows = rows
        self.running = False
        self.status_source = 'Diagnostics complete. An HTTP 401 response means the server requires authentication.'
        for widget in (
            self.host, self.port, self.tls, self.server_button,
            self.phone_qr_button, self.run_button,
        ):
            widget.setEnabled(True)
        self.update_qr_action()
        self.retranslate()

    def retranslate(self):
        language = self.controller.language
        language.apply(self.labels)
        self.table.setHorizontalHeaderLabels([language.text(s) for s in ('Check', 'Result', 'Details')])
        self.table.setRowCount(len(self.rows))
        for row, values in enumerate(self.rows):
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(language.text(value)))
        self.status.setText(language.text(self.status_source))
