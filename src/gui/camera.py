"""Explicit desktop camera capture and a shared latest-frame preview."""

import math
import time
from urllib.parse import urlsplit, urlunsplit

from PySide6.QtCore import QBuffer, QIODevice, QTimer, Qt, QEvent
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtMultimedia import (
    QAudioFormat, QAudioSource, QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QPushButton, QStyle, QSizePolicy, QSpinBox, QCheckBox, QProgressBar,
)

from ..core.camera import AudioFeed
from .network_tools import QRCodeDialog


RESOLUTIONS = ((320, 240), (640, 480), (960, 540), (1280, 720), (1920, 1080))
AUDIO_QUALITIES = (
    ('Low (8 kHz, mono)', 8000, 1),
    ('Voice (16 kHz, mono)', 16000, 1),
    ('Good (24 kHz, mono)', 24000, 1),
    ('High (48 kHz, stereo)', 48000, 2),
)


def audio_level(chunk):
    """Return the peak of 16-bit little-endian PCM as 0-100 over a 60 dB range."""
    samples = memoryview(chunk).cast('h')
    if not len(samples):
        return 0
    peak = max(max(samples), -min(samples))
    if peak <= 0:
        return 0
    return max(0, min(100, int(100 + 20 * math.log10(peak / 32768) * 100 / 60)))


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
        self.audio_source = self.audio_io = self.audio_session = None
        self.audio_pending = b''
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
        self.audio_check = QCheckBox(self)
        layout.addWidget(self.audio_check)
        self.audio_device = QComboBox(self)
        self.audio_device.setMinimumContentsLength(12)
        self.audio_device.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        layout.addWidget(self.audio_device)
        row = QHBoxLayout()
        self.audio_quality_label = QLabel(self)
        self.audio_quality = QComboBox(self)
        for label, rate, channels in AUDIO_QUALITIES:
            self.audio_quality.addItem(label, (rate, channels))
        self.audio_quality.setCurrentIndex(preference('audio_quality', 1, lambda value: 0 <= value < len(AUDIO_QUALITIES)))
        self.audio_quality_label.setBuddy(self.audio_quality)
        row.addWidget(self.audio_quality_label)
        row.addWidget(self.audio_quality)
        row.addStretch()
        layout.addLayout(row)
        self.audio_level_bar = QProgressBar(self)
        self.audio_level_bar.setRange(0, 100)
        self.audio_level_bar.setTextVisible(False)
        self.audio_level_bar.setMaximumHeight(10)
        layout.addWidget(self.audio_level_bar)
        self.audio_quality.currentIndexChanged.connect(self.change_audio_quality)
        self.audio_check.toggled.connect(self.update_actions)
        self.audio_mute = QCheckBox(self)
        layout.addWidget(self.audio_mute)
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

    def change_audio_quality(self):
        settings = getattr(self.controller, 'settings', None)
        if settings is not None:
            settings.setValue('camera/audio_quality', self.audio_quality.currentIndex())

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
        self.refresh_microphones()
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

    def refresh_microphones(self):
        list_inputs = getattr(QMediaDevices, 'audioInputs', None)
        if list_inputs is None:
            return
        previous = self.audio_device.currentData()
        previous_id = bytes(previous.id()) if previous else None
        self.audio_device.clear()
        try:
            default = QMediaDevices.defaultAudioInput()
            default_id = bytes(default.id()) if not default.isNull() else None
            for device in list_inputs():
                self.audio_device.addItem(device.description(), device)
                wanted = previous_id if previous_id is not None else default_id
                if bytes(device.id()) == wanted:
                    self.audio_device.setCurrentIndex(self.audio_device.count() - 1)
        except Exception as error:
            self.detail = str(error)

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
        else:
            if self.audio_check.isChecked() and self.session == token:
                self.start_audio()

    def start_audio(self):
        try:
            device = self.audio_device.currentData() or QMediaDevices.defaultAudioInput()
            if device.isNull():
                raise RuntimeError('No microphone found.')
            rate, channels = self.audio_quality.currentData()
            audio_format = QAudioFormat()
            audio_format.setSampleRate(rate)
            audio_format.setChannelCount(channels)
            audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if not device.isFormatSupported(audio_format):
                audio_format = device.preferredFormat()
                if (audio_format.sampleFormat() != QAudioFormat.SampleFormat.Int16
                        or audio_format.sampleRate() not in AudioFeed.RATES
                        or audio_format.channelCount() not in (1, 2)):
                    raise RuntimeError('The microphone format is not supported.')
            self.audio_pending = b''
            self.audio_session = self.feed.audio.start(audio_format.sampleRate(), audio_format.channelCount())
            self.audio_source = QAudioSource(device, audio_format, self)
            self.audio_io = self.audio_source.start()
            if self.audio_io is None:
                raise RuntimeError('Unable to open the microphone.')
            self.audio_io.readyRead.connect(self.read_audio)
        except Exception as error:
            self.stop_audio()
            self.detail = self.controller.language.text('Microphone unavailable; streaming video only.') + ' ' + str(error)
            self.retranslate()

    def read_audio(self):
        if not self.audio_io or not self.audio_session:
            return
        frame = 2 * self.feed.audio.channels
        data = self.audio_pending + bytes(self.audio_io.readAll())
        usable = len(data) - len(data) % frame
        self.audio_pending = data[usable:]
        if usable:
            chunk = bytes(usable) if self.audio_mute.isChecked() else data[:usable]
            self.audio_level_bar.setValue(audio_level(chunk))
            self.feed.audio.publish(self.audio_session, chunk)

    def stop_audio(self):
        source, self.audio_source, self.audio_io = self.audio_source, None, None
        session, self.audio_session = self.audio_session, None
        if source:
            source.stop()
            source.deleteLater()
        if session:
            self.feed.audio.stop(session)
        self.audio_pending = b''
        self.audio_level_bar.setValue(0)

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
        self.stop_audio()
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
        self.audio_check.setEnabled(not active)
        self.audio_device.setEnabled(not active and self.audio_check.isChecked())
        self.audio_mute.setEnabled(self.audio_check.isChecked())
        self.audio_quality.setEnabled(not active and self.audio_check.isChecked())
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
        self.note.setText(text('Share one selected camera through the HTTP server, without recording. Audio is optional and off by default. Choose 1 to 30 FPS; the actual rate depends on the camera and network. Use a LAN address for other devices.'))
        self.audio_check.setText(text('Include microphone audio (anyone who can open the camera page can listen)'))
        self.audio_mute.setText(text('Mute microphone (stream silence)'))
        self.audio_quality_label.setText(text('Audio quality:'))
        self.audio_quality.setAccessibleName(text('Audio quality:'))
        self.audio_quality.setToolTip(text('Higher audio quality uses more network bandwidth. Default: Voice.'))
        self.audio_level_bar.setAccessibleName(text('Microphone level'))
        for index, (label, _rate, _channels) in enumerate(AUDIO_QUALITIES):
            self.audio_quality.setItemText(index, text(label))
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
        self.audio_device.setAccessibleName(text('Microphone'))
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
