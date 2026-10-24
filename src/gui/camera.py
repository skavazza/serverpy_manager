"""Explicit desktop camera capture and a shared latest-frame preview."""

import time
from urllib.parse import urlsplit, urlunsplit

from PySide6.QtCore import QBuffer, QIODevice, QTimer, Qt, QEvent
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QPushButton, QStyle, QSizePolicy, QSpinBox,
)

from .network_tools import QRCodeDialog


RESOLUTIONS = ((320, 240), (640, 480), (960, 540), (1280, 720), (1920, 1080))


def choose_camera_format(device, bounds, fps):
    """Select only formats advertised by the device, preferring adequate FPS."""
    formats = list(device.videoFormats()) if hasattr(device, 'videoFormats') else []
    formats = [item for item in formats if item.resolution().width() > 0 and item.resolution().height() > 0]
    if not formats:
        return None
    covers = [item for item in formats if item.resolution().width() >= bounds[0] and item.resolution().height() >= bounds[1]]
    candidates = covers or formats
    fast = [item for item in candidates if item.maxFrameRate() >= fps]
    candidates = fast or candidates
    return min(candidates, key=lambda item: (
        item.resolution().width() * item.resolution().height() * (1 if covers else -1),
        -item.maxFrameRate(),
    ))


class CameraPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.feed = controller.server_manager.camera
        self.session = None
        self.camera = self.capture = self.sink = None
        self.last_frame = None
        self.started = 0
        self.was_active = False
        self.status_source = 'Start the HTTP server, then refresh and select a camera.'
        self.detail = ''
        settings = getattr(controller, 'settings', None)
        try:
            initial_fps = int(settings.value('camera/fps', 5)) if settings is not None else 5
        except (ValueError, TypeError):
            initial_fps = 5
        if not 1 <= initial_fps <= 30:
            initial_fps = 5
        self.feed.set_fps(initial_fps)
        def preference(name, default, valid):
            try:
                value = int(settings.value('camera/' + name, default)) if settings is not None else default
                return value if valid(value) else default
            except (ValueError, TypeError):
                return default
        initial_quality = preference('quality', 75, lambda value: 10 <= value <= 95)
        initial_resolution = preference('resolution_width', 960, lambda value: value in [width for width, _ in RESOLUTIONS])
        layout = QVBoxLayout(self)
        self.note = QLabel(self)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        row = QHBoxLayout()
        self.devices = QComboBox(self)
        self.devices.setMinimumContentsLength(12)
        self.devices.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.devices, 1)
        self.refresh_button = self.button(QStyle.SP_BrowserReload)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.resolution_label = QLabel(self)
        self.resolution = QComboBox(self)
        for width, height in RESOLUTIONS:
            self.resolution.addItem(f'{width} × {height}', (width, height))
        self.resolution.setCurrentIndex([width for width, _ in RESOLUTIONS].index(initial_resolution))
        self.resolution_label.setBuddy(self.resolution)
        row.addWidget(self.resolution_label)
        row.addWidget(self.resolution)
        row.addStretch()
        layout.addLayout(row)
        row = QHBoxLayout()
        self.quality_label = QLabel(self)
        self.quality = QSpinBox(self)
        self.quality.setRange(10, 95)
        self.quality.setSuffix(' %')
        self.quality.setValue(initial_quality)
        self.quality_label.setBuddy(self.quality)
        row.addWidget(self.quality_label)
        row.addWidget(self.quality)
        row.addStretch()
        layout.addLayout(row)
        row = QHBoxLayout()
        self.fps_label = QLabel(self)
        self.fps = QSpinBox(self)
        self.fps.setRange(1, 30)
        self.fps.setSuffix(' FPS')
        self.fps.setValue(initial_fps)
        self.fps_label.setBuddy(self.fps)
        row.addWidget(self.fps_label)
        row.addWidget(self.fps)
        row.addStretch()
        layout.addLayout(row)
        row = QHBoxLayout()
        self.start_button = self.button(QStyle.SP_MediaPlay)
        self.stop_button = self.button(QStyle.SP_MediaStop)
        row.addWidget(self.start_button)
        row.addWidget(self.stop_button)
        layout.addLayout(row)
        self.preview = QLabel(self)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(240, 150)
        self.preview.setMaximumHeight(320)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.preview.setStyleSheet('background: #06090e; color: #cdd8e7; border: 1px solid #43546a;')
        layout.addWidget(self.preview)
        self.status = QLabel(self)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.metrics = QLabel(self)
        self.metrics.setWordWrap(True)
        layout.addWidget(self.metrics)
        self.url = QLineEdit(self)
        self.url.setReadOnly(True)
        layout.addWidget(self.url)
        row = QHBoxLayout()
        self.copy_button = self.button(QStyle.SP_FileIcon)
        self.open_button = self.button(QStyle.SP_DirLinkIcon)
        self.qr_button = self.button(QStyle.SP_DialogHelpButton)
        for button in (self.copy_button, self.open_button, self.qr_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.refresh_button.clicked.connect(self.refresh)
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(lambda: self.stop())
        self.devices.currentIndexChanged.connect(self.update_actions)
        self.fps.valueChanged.connect(self.change_fps)
        self.resolution.currentIndexChanged.connect(self.change_image_settings)
        self.quality.valueChanged.connect(self.change_image_settings)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.url.text()))
        self.open_button.clicked.connect(lambda: QDesktopServices.openUrl(self.url_to_qt()))
        self.qr_button.clicked.connect(self.show_qr)
        self.monitor = QTimer(self)
        self.monitor.setInterval(250)
        self.monitor.timeout.connect(self.check_capture)
        self.media_devices = QMediaDevices(self)
        self.media_devices.videoInputsChanged.connect(self.devices_changed)
        QApplication.instance().aboutToQuit.connect(self.stop)
        controller.window.installEventFilter(self)
        combo = getattr(controller, 'access_combo', None)
        if combo is not None:
            combo.currentIndexChanged.connect(self.update_actions)
        self.retranslate()

    def button(self, icon):
        button = QPushButton(self)
        button.setIcon(self.style().standardIcon(icon))
        return button

    def change_fps(self, fps):
        self.feed.set_fps(fps)
        settings = getattr(self.controller, 'settings', None)
        if settings is not None:
            settings.setValue('camera/fps', fps)
        if self.camera:
            self.apply_camera_format()
        self.retranslate()

    def change_image_settings(self):
        settings = getattr(self.controller, 'settings', None)
        if settings is not None:
            settings.setValue('camera/resolution_width', self.resolution.currentData()[0])
            settings.setValue('camera/quality', self.quality.value())
        if self.camera:
            self.apply_camera_format()
        self.retranslate()

    def apply_camera_format(self):
        try:
            selected = choose_camera_format(self.devices.currentData(), self.resolution.currentData(), self.feed.fps)
            if selected is not None and selected != getattr(self, 'selected_format', None):
                self.selected_format = selected
                self.camera.setCameraFormat(selected)
        except Exception as error:
            self.stop('Unable to apply the camera resolution.', str(error))

    def url_to_qt(self):
        from PySide6.QtCore import QUrl
        return QUrl(self.url.text())

    def show_qr(self):
        if self.session and self.url.text():
            QRCodeDialog(self.url.text(), self, self.controller.language).exec()

    def eventFilter(self, watched, event):
        if watched is self.controller.window and event.type() == QEvent.Close:
            self.stop()
        return False

    def refresh(self):
        if self.session:
            return
        previous = self.devices.currentData()
        previous_id = bytes(previous.id()) if previous else None
        self.devices.clear()
        try:
            for device in QMediaDevices.videoInputs():
                self.devices.addItem(device.description(), device)
                if bytes(device.id()) == previous_id:
                    self.devices.setCurrentIndex(self.devices.count() - 1)
            self.status_source = 'Select a camera and click Start streaming.' if self.devices.count() else 'No cameras found. Connect a camera and check camera permissions.'
            self.detail = ''
        except Exception as error:
            self.status_source = 'Unable to list cameras.'
            self.detail = str(error)
        self.retranslate()

    def devices_changed(self):
        if self.session:
            selected = self.devices.currentData()
            if selected and not any(bytes(device.id()) == bytes(selected.id()) for device in QMediaDevices.videoInputs()):
                self.stop('Camera disconnected. Refresh the camera list.')
        else:
            self.refresh()

    def start(self):
        if self.session or not self.controller.server_manager.is_running:
            return
        device = self.devices.currentData()
        if device is None:
            return
        token = self.feed.start()
        self.session = token
        self.started = time.monotonic()
        self.last_frame = None
        self.was_active = False
        self.detail = ''
        self.status_source = 'Starting camera...'
        try:
            self.camera = QCamera(device, self)
            self.selected_format = None
            self.capture = QMediaCaptureSession(self)
            self.sink = QVideoSink(self)
            self.capture.setCamera(self.camera)
            self.capture.setVideoSink(self.sink)
            self.sink.videoFrameChanged.connect(lambda frame, token=token: self.on_frame(frame, token))
            self.camera.errorOccurred.connect(lambda error, detail, token=token: self.camera_error(error, detail, token))
            self.camera.activeChanged.connect(lambda active, token=token: self.active_changed(active, token))
            self.apply_camera_format()
            if not self.session:
                return
            self.monitor.start()
            self.retranslate()
            self.camera.start()
        except Exception as error:
            self.stop('Unable to start the camera.', str(error))

    def active_changed(self, active, token):
        if self.session != token:
            return
        if active:
            self.was_active = True
        elif self.was_active:
            self.stop('Camera stopped by the device. Check permissions or other camera applications.')

    def camera_error(self, error, detail, token):
        if self.session == token:
            self.stop('Camera error. Check permissions or other camera applications.', detail)

    def on_frame(self, frame, token):
        if self.session != token or not self.feed.is_current(token):
            return
        now = time.monotonic()
        if self.last_frame is not None and now - self.last_frame < 1 / self.feed.fps:
            return
        image = frame.toImage()
        if image.isNull():
            return
        width, height = self.resolution.currentData()
        if image.width() > width or image.height() > height:
            image = image.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        if not image.save(buffer, 'JPEG', self.quality.value()):
            return
        if not self.feed.publish(token, bytes(buffer.data()), size=(image.width(), image.height())):
            if self.feed.is_current(token):
                self.stop('Camera image is too large. Lower the resolution or JPEG quality.')
            return
        self.last_frame = now
        self.preview.setPixmap(QPixmap.fromImage(image).scaled(
            max(1, self.preview.width()), max(150, self.preview.height()), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.status_source = 'Camera live: up to {fps} frames per second. Clients use the HTTP server access settings.'
        self.retranslate()

    def stop(self, source='Camera is off.', detail=''):
        token, self.session = self.session, None
        if token:
            self.feed.stop(token)
        self.monitor.stop()
        camera, capture, sink = self.camera, self.capture, self.sink
        self.camera = self.capture = self.sink = None
        if camera:
            camera.stop()
        if capture:
            capture.setCamera(None)
            capture.setVideoSink(None)
        for item in (camera, capture, sink):
            if item:
                item.deleteLater()
        self.preview.clear()
        self.last_frame = None
        self.status_source, self.detail = source, detail
        self.retranslate()

    def check_capture(self):
        self.update_metrics()
        if not self.session:
            return
        if not self.controller.server_manager.is_running or not self.feed.is_current(self.session):
            self.stop('Camera stopped with the HTTP server.')
            return
        elapsed = time.monotonic() - (self.last_frame if self.last_frame is not None else self.started)
        if elapsed > (5 if self.last_frame is not None else 10):
            self.stop('No camera frames received. Check the device and start again.')
        elif self.last_frame is not None and elapsed > self.feed.MAX_AGE:
            self.preview.clear()
            self.preview.setText(self.controller.language.text('Waiting for a fresh camera image...'))

    def update_metrics(self):
        stats = self.feed.stats()
        self.metrics.setText(self.controller.language.text(
            'Published: {actual:.1f} FPS | Requested: {requested} FPS | Image: {width} × {height}',
            actual=stats['published_fps'], requested=self.feed.fps, width=stats['width'], height=stats['height']))

    def update_actions(self):
        manager = self.controller.server_manager
        if self.session and (not manager.is_running or not self.feed.is_current(self.session)):
            self.stop('Camera stopped with the HTTP server.')
            return
        active = self.session is not None
        self.devices.setEnabled(not active)
        self.refresh_button.setEnabled(not active)
        self.start_button.setEnabled(not active and manager.is_running and self.devices.currentData() is not None)
        self.stop_button.setEnabled(active)
        combo = getattr(self.controller, 'access_combo', None)
        address = combo.currentData() if combo is not None else None
        parts = urlsplit(address or '')
        self.url.setText(urlunsplit((parts.scheme, parts.netloc, '/_camera/', '', '')) if manager.is_running and parts.netloc else '')
        for button in (self.copy_button, self.open_button, self.qr_button):
            button.setEnabled(active and bool(self.url.text()))

    def retranslate(self):
        text = self.controller.language.text
        self.note.setText(text('Share one selected camera through the HTTP server, without audio or recording. Choose 1 to 30 FPS; the actual rate depends on the camera and network. Use a LAN address for other devices.'))
        self.fps_label.setText(text('Transmission frame rate:'))
        self.fps.setAccessibleName(text('Transmission frame rate:'))
        self.fps.setToolTip(text('Changes apply while streaming. Default: 5 FPS.'))
        self.resolution_label.setText(text('Maximum transmission resolution:'))
        self.resolution.setAccessibleName(text('Maximum transmission resolution:'))
        self.resolution.setToolTip(text('Preserves proportions and never enlarges the camera image.'))
        self.quality_label.setText(text('JPEG quality:'))
        self.quality.setAccessibleName(text('JPEG quality:'))
        self.quality.setToolTip(text('Higher quality uses more network bandwidth. Default: 75%.'))
        self.update_metrics()
        self.devices.setAccessibleName(text('Camera'))
        self.url.setAccessibleName(text('Camera viewer URL'))
        for button, source in (
            (self.refresh_button, 'Refresh cameras'), (self.start_button, 'Start streaming'),
            (self.stop_button, 'Stop streaming'), (self.copy_button, 'Copy camera URL'),
            (self.open_button, 'Open camera viewer'), (self.qr_button, 'Camera QR Code'),
        ):
            button.setText(text(source))
        self.status.setText(text(self.status_source, fps=self.fps.value()) + ('\n' + self.detail if self.detail else ''))
        if self.last_frame is None:
            self.preview.setText(text('Camera is off.') if self.session is None else text('Waiting for a fresh camera image...'))
        self.update_actions()
