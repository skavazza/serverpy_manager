"""Storage tab: discover drives without blocking the GUI and share their files."""

import os
import sys
import posixpath
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt, QProcess, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QLineEdit, QTreeWidget, QTreeWidgetItem, QFileDialog,
    QMessageBox, QGroupBox, QProgressBar, QGridLayout, QCheckBox,
    QSpinBox,
)

from ..core.storage import list_external_drives
from ..core.android import (
    android_adb_available, android_adb_install_supported,
    capture_android_screenshot, install_android_apk,
    install_android_platform_tools, list_android_devices,
    list_android_directory, send_android_control, transfer_android_file,
    set_android_reverse,
)
from ..core.scrcpy import (
    install_scrcpy, scrcpy_available, scrcpy_download_supported,
    scrcpy_executable,
)


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


class _AndroidTask(QRunnable):
    def __init__(self, action, operation):
        super().__init__()
        self.action = action
        self.operation = operation
        self.signals = _ScanSignals()

    def run(self):
        operation = self.operation
        self.operation = None
        try:
            result = True, (
                operation(self.signals.progress.emit)
                if self.action in ('install_adb', 'install_scrcpy') else operation()
            )
        except (FileNotFoundError, OSError, TimeoutError, ValueError) as error:
            result = False, str(error)
        self.signals.finished.emit(True, (self.action, *result))


class AndroidDevicePanel(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.devices = []
        self.devices_loaded = False
        self.loading = False
        self.remote_path = '/sdcard/Download'
        self.reverse_port = None
        self.status_source = 'Connect an Android phone with USB debugging enabled, authorize this computer, then refresh.'
        self.status_values = {}
        self.reverse_url = ''
        self.scrcpy_output = ''
        self.scrcpy_stopping = False
        self.scrcpy_record_path = ''
        self.scrcpy_process = QProcess(self)
        self.scrcpy_process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels,
        )
        self.scrcpy_process.started.connect(self.scrcpy_started)
        self.scrcpy_process.finished.connect(self.scrcpy_finished)
        self.scrcpy_process.errorOccurred.connect(self.scrcpy_error)
        self.scrcpy_process.readyReadStandardOutput.connect(self.capture_scrcpy_output)
        self.layout_box = QVBoxLayout(self)
        row = QHBoxLayout()
        self.device = QComboBox(self)
        self.refresh_button = QPushButton('Refresh Android devices', self)
        self.install_adb_button = QPushButton('Install Android platform tools', self)
        row.addWidget(self.device, 1)
        row.addWidget(self.refresh_button)
        self.layout_box.addLayout(row)
        install_row = QHBoxLayout()
        install_row.addWidget(self.install_adb_button)
        self.install_scrcpy_button = QPushButton('Install scrcpy screen control', self)
        install_row.addWidget(self.install_scrcpy_button)
        install_row.addStretch()
        self.layout_box.addLayout(install_row)
        session_row = QHBoxLayout()
        self.start_scrcpy_button = QPushButton('Start screen control', self)
        self.stop_scrcpy_button = QPushButton('Stop screen control', self)
        session_row.addWidget(self.start_scrcpy_button)
        session_row.addWidget(self.stop_scrcpy_button)
        session_row.addStretch()
        self.layout_box.addLayout(session_row)
        session_options = QHBoxLayout()
        self.clipboard_sync = QCheckBox(
            'Enable clipboard synchronization (Android apps may read pasted text)',
            self,
        )
        self.record_scrcpy = QCheckBox('Record this scrcpy session', self)
        session_options.addWidget(self.clipboard_sync)
        session_options.addWidget(self.record_scrcpy)
        session_options.addStretch()
        self.layout_box.addLayout(session_options)
        settings_row = QHBoxLayout()
        self.video_settings_group = QGroupBox('Video settings', self)
        video_settings = QGridLayout(self.video_settings_group)
        self.resolution_label = QLabel('Resolution', self.video_settings_group)
        self.resolution = QComboBox(self.video_settings_group)
        self.resolution.addItem('Original', 0)
        self.resolution.addItem('1080p', 1920)
        self.resolution.addItem('720p', 1280)
        self.resolution.addItem('480p', 800)
        self.codec_label = QLabel('Video codec', self.video_settings_group)
        self.video_codec = QComboBox(self.video_settings_group)
        for label, codec in (('H.264', 'h264'), ('H.265', 'h265'), ('AV1', 'av1')):
            self.video_codec.addItem(label, codec)
        self.fps_label = QLabel('Frame rate', self.video_settings_group)
        self.max_fps = QComboBox(self.video_settings_group)
        self.max_fps.addItem('Auto', 0)
        self.max_fps.addItem('30 FPS', 30)
        self.max_fps.addItem('60 FPS', 60)
        self.bitrate_label = QLabel('Video bitrate', self.video_settings_group)
        self.video_bitrate = QSpinBox(self.video_settings_group)
        self.video_bitrate.setRange(2, 32)
        self.video_bitrate.setSuffix(' Mbps')
        self.video_bitrate.setValue(8)
        self.display_orientation_label = QLabel(
            'Display orientation', self.video_settings_group,
        )
        self.display_orientation = QComboBox(self.video_settings_group)
        self.display_orientation.addItem('Device default', None)
        for label, orientation in (
            ('0°', '0'),
            ('90°', '90'),
            ('180°', '180'),
            ('Flip 0°', 'flip0'),
            ('Flip 90°', 'flip90'),
            ('Flip 180°', 'flip180'),
            ('Flip 270°', 'flip270'),
        ):
            self.display_orientation.addItem(label, orientation)
        for row_index, (label, control) in enumerate((
            (self.resolution_label, self.resolution),
            (self.codec_label, self.video_codec),
            (self.fps_label, self.max_fps),
            (self.bitrate_label, self.video_bitrate),
        )):
            video_settings.addWidget(label, row_index, 0)
            video_settings.addWidget(control, row_index, 1)
        video_settings.addWidget(self.display_orientation_label, 4, 0)
        video_settings.addWidget(self.display_orientation, 4, 1)
        settings_row.addWidget(self.video_settings_group, 1)

        self.session_settings_group = QGroupBox('Session behavior', self)
        session_settings = QGridLayout(self.session_settings_group)
        self.stay_awake = QCheckBox('Keep device awake', self.session_settings_group)
        self.turn_screen_off = QCheckBox('Turn device screen off', self.session_settings_group)
        self.always_on_top = QCheckBox('Always on top', self.session_settings_group)
        self.fullscreen = QCheckBox('Start fullscreen', self.session_settings_group)
        self.borderless = QCheckBox('Borderless window', self.session_settings_group)
        self.session_setting_checks = (
            self.stay_awake,
            self.turn_screen_off,
            self.always_on_top,
            self.fullscreen,
            self.borderless,
        )
        for index, checkbox in enumerate(self.session_setting_checks):
            session_settings.addWidget(checkbox, index // 2, index % 2)
        settings_row.addWidget(self.session_settings_group, 1)
        self.layout_box.addLayout(settings_row)

        self.audio_settings_group = QGroupBox('Audio settings', self)
        audio_settings = QGridLayout(self.audio_settings_group)
        self.forward_audio = QCheckBox('Forward audio', self.audio_settings_group)
        self.forward_audio.setChecked(True)
        self.audio_source_label = QLabel('Audio source', self.audio_settings_group)
        self.audio_source = QComboBox(self.audio_settings_group)
        for label, source in (
            ('Device output', 'output'),
            ('Playback capture', 'playback'),
            ('Microphone', 'mic'),
            ('Unprocessed microphone', 'mic-unprocessed'),
            ('Camcorder microphone', 'mic-camcorder'),
            ('Voice recognition microphone', 'mic-voice-recognition'),
            ('Voice communication microphone', 'mic-voice-communication'),
            ('Voice call', 'voice-call'),
            ('Voice call uplink', 'voice-call-uplink'),
            ('Voice call downlink', 'voice-call-downlink'),
            ('Voice performance', 'voice-performance'),
        ):
            self.audio_source.addItem(label, source)
        self.audio_codec_label = QLabel('Audio codec', self.audio_settings_group)
        self.audio_codec = QComboBox(self.audio_settings_group)
        for codec in ('opus', 'aac', 'flac', 'raw'):
            self.audio_codec.addItem(codec.upper(), codec)
        self.audio_bitrate_label = QLabel('Audio bitrate', self.audio_settings_group)
        self.audio_bitrate = QComboBox(self.audio_settings_group)
        for label, bitrate in (
            ('64 Kbps', '64K'),
            ('128 Kbps', '128K'),
            ('256 Kbps', '256K'),
            ('512 Kbps', '512K'),
        ):
            self.audio_bitrate.addItem(label, bitrate)
        self.audio_bitrate.setCurrentIndex(self.audio_bitrate.findData('128K'))
        audio_settings.addWidget(self.forward_audio, 0, 0)
        audio_settings.addWidget(self.audio_source_label, 0, 1)
        audio_settings.addWidget(self.audio_source, 0, 2)
        audio_settings.addWidget(self.audio_codec_label, 0, 3)
        audio_settings.addWidget(self.audio_codec, 0, 4)
        audio_settings.addWidget(self.audio_bitrate_label, 0, 5)
        audio_settings.addWidget(self.audio_bitrate, 0, 6)
        self.layout_box.addWidget(self.audio_settings_group)
        self.forward_audio.toggled.connect(self.update_actions)

        self.scrcpy_settings = (
            self.resolution,
            self.video_codec,
            self.max_fps,
            self.video_bitrate,
            self.display_orientation,
            self.audio_source,
            self.audio_codec,
            self.audio_bitrate,
            *self.session_setting_checks,
        )
        self.controls_group = QGroupBox('Phone controls', self)
        controls_layout = QGridLayout(self.controls_group)
        control_rows = (
            (
                ('back', 'Back'),
                ('home', 'Home'),
                ('recent_apps', 'Recent apps'),
                ('power', 'Power'),
            ),
            (
                ('screen_on', 'Wake screen'),
                ('screen_off', 'Sleep screen'),
                ('volume_up', 'Volume up'),
                ('volume_down', 'Volume down'),
            ),
            (
                ('rotate', 'Rotate screen'),
                ('auto_rotation', 'Restore auto-rotation'),
                ('notifications', 'Notifications'),
                ('quick_settings', 'Quick settings'),
                ('collapse_panels', 'Close panels'),
            ),
        )
        self.control_buttons = {}
        for row_index, controls in enumerate(control_rows):
            for column_index, (action, label) in enumerate(controls):
                button = QPushButton(label, self.controls_group)
                button.clicked.connect(
                    lambda _checked=False, action=action: self.run_android_control(action)
                )
                controls_layout.addWidget(button, row_index, column_index)
                self.control_buttons[action] = button
        self.rotation_note = QLabel(
            'Manual rotation disables auto-rotate until you restore it.',
            self.controls_group,
        )
        self.rotation_note.setWordWrap(True)
        controls_layout.addWidget(self.rotation_note, len(control_rows), 0, 1, 5)
        self.layout_box.addWidget(self.controls_group)

        path_row = QHBoxLayout()
        self.path = QLineEdit(self.remote_path, self)
        self.go_button = QPushButton('Go', self)
        self.parent_button = QPushButton('Parent folder', self)
        path_row.addWidget(self.path, 1)
        path_row.addWidget(self.go_button)
        path_row.addWidget(self.parent_button)
        self.layout_box.addLayout(path_row)

        self.entries = QTreeWidget(self)
        self.entries.setHeaderLabels(['Name', 'Type'])
        self.entries.setSelectionMode(QAbstractItemView.SingleSelection)
        self.entries.setMinimumHeight(130)
        self.layout_box.addWidget(self.entries)

        actions = QHBoxLayout()
        self.pull_button = QPushButton('Download from phone', self)
        self.push_button = QPushButton('Send file to phone', self)
        actions.addWidget(self.pull_button)
        actions.addWidget(self.push_button)
        self.install_apk_button = QPushButton('Install APK...', self)
        self.screenshot_button = QPushButton('Capture screenshot...', self)
        actions.addWidget(self.install_apk_button)
        actions.addWidget(self.screenshot_button)
        self.layout_box.addLayout(actions)
        tunnel_actions = QHBoxLayout()
        self.reverse_button = QPushButton('Enable USB access to HTTP server', self)
        self.remove_reverse_button = QPushButton('Remove USB access', self)
        tunnel_actions.addWidget(self.reverse_button)
        tunnel_actions.addWidget(self.remove_reverse_button)
        self.layout_box.addLayout(tunnel_actions)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        self.layout_box.addWidget(self.status)
        self.install_progress = QProgressBar(self)
        self.install_progress.setRange(0, 0)
        self.install_progress.setVisible(False)
        self.layout_box.addWidget(self.install_progress)

        self.refresh_button.clicked.connect(self.refresh_devices)
        self.install_adb_button.clicked.connect(self.install_adb)
        self.install_scrcpy_button.clicked.connect(self.install_scrcpy_tools)
        self.start_scrcpy_button.clicked.connect(self.start_scrcpy)
        self.stop_scrcpy_button.clicked.connect(self.stop_scrcpy)
        self.device.currentIndexChanged.connect(self.device_changed)
        self.go_button.clicked.connect(lambda: self.load_directory(self.path.text()))
        self.parent_button.clicked.connect(self.parent_directory)
        self.entries.itemDoubleClicked.connect(self.open_entry)
        self.entries.itemSelectionChanged.connect(self.update_actions)
        self.pull_button.clicked.connect(self.pull_selected)
        self.push_button.clicked.connect(self.push_file)
        self.install_apk_button.clicked.connect(self.install_apk)
        self.screenshot_button.clicked.connect(self.capture_screenshot)
        self.reverse_button.clicked.connect(lambda: self.set_reverse(True))
        self.remove_reverse_button.clicked.connect(lambda: self.set_reverse(False))
        self.labels = controller.language.capture(self)
        self.retranslate()
        application = getattr(controller, 'app', None)
        if application is not None:
            application.aboutToQuit.connect(self.shutdown_scrcpy)

    def selected_device(self):
        device = self.device.currentData()
        return device if isinstance(device, dict) and device['state'] == 'device' else None

    def refresh_devices(self):
        if self.loading:
            return
        self.devices_loaded = True
        self.start_task('devices', list_android_devices)

    def install_adb(self):
        if self.loading or android_adb_available() or not android_adb_install_supported():
            return
        answer = QMessageBox.question(
            self,
            self.controller.language.text('Install Android platform tools?'),
            self.controller.language.text(
                'Download the official Google Android Platform-Tools package and install it for this user only?'
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.install_progress.setRange(0, 0)
        self.install_progress.setValue(0)
        self.install_progress.setVisible(True)
        self.start_task('install_adb', install_android_platform_tools)

    def install_scrcpy_tools(self):
        if self.loading or scrcpy_available() or not scrcpy_download_supported():
            return
        answer = QMessageBox.question(
            self,
            self.controller.language.text('Install scrcpy screen control?'),
            self.controller.language.text(
                'Download the official Genymobile scrcpy release and install it for this user only?'
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.install_progress.setRange(0, 0)
        self.install_progress.setValue(0)
        self.install_progress.setVisible(True)
        self.start_task('install_scrcpy', install_scrcpy)

    def start_scrcpy(self):
        device = self.selected_device()
        if not device or self.scrcpy_process.state() != QProcess.ProcessState.NotRunning:
            return
        executable = scrcpy_executable()
        if not executable:
            self.status_source = 'Install scrcpy before starting screen control.'
            self.error_detail = ''
            self.retranslate()
            return
        self.scrcpy_output = ''
        self.scrcpy_stopping = False
        self.scrcpy_record_path = ''
        arguments = [
            '--serial', device['serial'],
            '--window-title', f"ServerPy - {device['model'] or device['serial']}",
        ]
        resolution = self.resolution.currentData()
        if resolution:
            arguments.extend(['--max-size', str(resolution)])
        codec = self.video_codec.currentData()
        if codec != 'h264':
            arguments.extend(['--video-codec', codec])
        max_fps = self.max_fps.currentData()
        if max_fps:
            arguments.extend(['--max-fps', str(max_fps)])
        bitrate = self.video_bitrate.value()
        if bitrate != 8:
            arguments.extend(['--video-bit-rate', f'{bitrate}M'])
        orientation = self.display_orientation.currentData()
        if orientation is not None:
            arguments.extend(['--display-orientation', orientation])
        if not self.clipboard_sync.isChecked():
            arguments.append('--no-clipboard-autosync')
        if not self.forward_audio.isChecked():
            arguments.append('--no-audio')
        else:
            audio_source = self.audio_source.currentData()
            if audio_source != 'output':
                arguments.extend(['--audio-source', audio_source])
            audio_codec = self.audio_codec.currentData()
            if audio_codec != 'opus':
                arguments.extend(['--audio-codec', audio_codec])
            audio_bitrate = self.audio_bitrate.currentData()
            if audio_bitrate != '128K':
                arguments.extend(['--audio-bit-rate', audio_bitrate])
        for checkbox, option in (
            (self.stay_awake, '--stay-awake'),
            (self.turn_screen_off, '--turn-screen-off'),
            (self.always_on_top, '--always-on-top'),
            (self.fullscreen, '--fullscreen'),
            (self.borderless, '--window-borderless'),
        ):
            if checkbox.isChecked():
                arguments.append(option)
        if self.record_scrcpy.isChecked():
            target, _ = QFileDialog.getSaveFileName(
                self, self.controller.language.text('Save scrcpy recording'),
                f"android-{device['serial']}.mp4",
                self.controller.language.text('MP4 video (*.mp4)'),
            )
            if not target:
                return
            if not target.lower().endswith('.mp4'):
                target += '.mp4'
            if os.path.exists(target) and QMessageBox.question(
                self, self.controller.language.text('Overwrite file?'),
                self.controller.language.text('Replace the selected local file?'),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            self.scrcpy_record_path = target
            arguments.extend(['--record', target])
        self.status_source = 'Starting scrcpy screen control...'
        self.error_detail = ''
        self.scrcpy_process.setProgram(executable)
        self.scrcpy_process.setArguments(arguments)
        self.scrcpy_process.start()
        self.update_actions()
        self.retranslate()

    def stop_scrcpy(self):
        if self.scrcpy_process.state() == QProcess.ProcessState.NotRunning:
            return
        self.scrcpy_stopping = True
        self.status_source = 'Stopping scrcpy screen control...'
        self.error_detail = ''
        self.scrcpy_process.terminate()
        QTimer.singleShot(3000, self.kill_scrcpy_if_running)
        self.update_actions()
        self.retranslate()

    def kill_scrcpy_if_running(self):
        if self.scrcpy_process.state() != QProcess.ProcessState.NotRunning:
            self.scrcpy_process.kill()

    def shutdown_scrcpy(self):
        if self.scrcpy_process.state() == QProcess.ProcessState.NotRunning:
            return
        self.scrcpy_stopping = True
        self.scrcpy_process.terminate()
        if not self.scrcpy_process.waitForFinished(2000):
            self.scrcpy_process.kill()
            self.scrcpy_process.waitForFinished(1000)

    def capture_scrcpy_output(self):
        output = bytes(self.scrcpy_process.readAllStandardOutput()).decode(
            'utf-8', errors='replace',
        )
        self.scrcpy_output = (self.scrcpy_output + output)[-4000:]

    def scrcpy_started(self):
        self.status_source = 'scrcpy screen control is running in its own window.'
        self.error_detail = ''
        self.update_actions()
        self.retranslate()

    def scrcpy_finished(self, exit_code, _exit_status):
        self.capture_scrcpy_output()
        if self.scrcpy_stopping:
            self.status_source = 'scrcpy screen control stopped.'
            self.error_detail = (
                self.controller.language.text('Recording saved to {path}', path=self.scrcpy_record_path)
                if self.scrcpy_record_path and exit_code == 0 else ''
            )
        elif exit_code:
            self.status_source = 'scrcpy screen control exited with an error.'
            self.error_detail = self.scrcpy_output.strip()
        else:
            self.status_source = 'scrcpy screen control ended.'
            self.error_detail = (
                self.controller.language.text('Recording saved to {path}', path=self.scrcpy_record_path)
                if self.scrcpy_record_path else ''
            )
        self.scrcpy_stopping = False
        self.update_actions()
        self.retranslate()

    def scrcpy_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.status_source = 'Unable to start scrcpy screen control.'
            self.error_detail = self.scrcpy_process.errorString()
            self.update_actions()
            self.retranslate()

    def device_changed(self, _index=None):
        self.entries.clear()
        selected = self.selected_device()
        if selected:
            self.load_directory(self.remote_path)
        else:
            self.update_actions()

    def load_directory(self, remote_path):
        device = self.selected_device()
        if not device or self.loading:
            return
        path = posixpath.normpath(remote_path.strip() or '/')
        if not path.startswith('/'):
            path = '/' + path
        self.remote_path = path
        self.path.setText(path)
        self.start_task(
            'directory',
            lambda: list_android_directory(device['serial'], path),
        )

    def start_task(self, action, operation):
        if self.loading:
            return
        self.loading = True
        if action == 'install_adb':
            self.status_source = 'Downloading and verifying Android Platform-Tools...'
        elif action == 'install_scrcpy':
            self.status_source = 'Downloading and verifying the official scrcpy release...'
        else:
            self.status_source = 'Working with Android device...'
        self.status_values = {}
        self.error_detail = ''
        self.update_actions()
        self.retranslate()
        self.task = _AndroidTask(action, operation)
        self.task.signals.finished.connect(self.task_finished)
        self.task.signals.progress.connect(self.install_progress_updated)
        QThreadPool.globalInstance().start(self.task)

    def install_progress_updated(self, downloaded, total):
        if total > 0:
            self.install_progress.setRange(0, 100)
            self.install_progress.setValue(min(100, downloaded * 100 // total))
        else:
            self.install_progress.setRange(0, 0)

    def task_finished(self, _ok, result):
        action, ok, value = result
        self.loading = False
        if action in ('install_adb', 'install_scrcpy'):
            self.install_progress.setVisible(False)
            if action == 'install_adb':
                self.status_source = (
                    'Android Platform-Tools installed. Refresh devices to continue.'
                    if ok else 'Unable to install Android Platform-Tools.'
                )
            else:
                self.status_source = (
                    'Official scrcpy installed for this user.'
                    if ok else 'Unable to install scrcpy.'
                )
            self.error_detail = '' if ok else str(value)
            self.retranslate()
            return
        if action == 'devices':
            self.devices = value if ok else []
            self.device.blockSignals(True)
            self.device.clear()
            for item in self.devices:
                label = item['model'] or item['serial']
                if item['state'] != 'device':
                    label += f" ({item['state']})"
                self.device.addItem(label, item)
            self.device.blockSignals(False)
            if ok and self.selected_device():
                self.status_source = 'Android device found.'
                self.load_directory(self.remote_path)
                return
            self.status_source = (
                'No authorized Android device found. Check USB debugging and approve the computer on the phone.'
                if ok else 'Unable to query Android devices.'
            )
            value = '' if ok else value
        elif action == 'directory':
            if ok:
                self.entries.clear()
                for entry in value:
                    item = QTreeWidgetItem([
                        entry['name'],
                        'Folder' if entry['is_dir'] else 'File',
                    ])
                    item.setData(0, Qt.UserRole, entry)
                    self.entries.addTopLevelItem(item)
                self.status_source = 'Android folder loaded.'
            else:
                self.status_source = 'Unable to list Android folder.'
        elif action == 'transfer':
            self.status_source = 'Android file transfer completed.' if ok else 'Android file transfer failed.'
        elif action == 'control':
            self.status_source = 'Android control action completed.' if ok else 'Android control action failed.'
        elif action == 'apk':
            self.status_source = 'Android APK installation completed.' if ok else 'Android APK installation failed.'
        elif action == 'screenshot':
            self.status_source = 'Android screenshot saved.' if ok else 'Unable to capture Android screenshot.'
        elif action == 'reverse':
            enabled, output = value
            self.status_source = (
                'USB access enabled. Open {url} in the phone browser.'
                if ok and enabled else
                'USB access removed.' if ok else
                'Unable to change USB access.'
            )
            self.error_detail = output if ok and output else ('' if ok else str(value))
            self.status_values = {'url': self.reverse_url} if ok and enabled else {}
            if ok and not enabled:
                self.reverse_port = None
            self.retranslate()
            return
        self.error_detail = str(value) if not ok else ''
        self.retranslate()

    def selected_entry(self):
        item = self.entries.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def run_android_control(self, action):
        device = self.selected_device()
        if not device or self.loading:
            return
        self.start_task(
            'control',
            lambda: send_android_control(device['serial'], action),
        )

    def install_apk(self):
        device = self.selected_device()
        if not device or self.loading:
            return
        source, _ = QFileDialog.getOpenFileName(
            self, self.controller.language.text('Select Android APK'),
            filter=self.controller.language.text('Android APK files (*.apk)'),
        )
        if not source:
            return
        if QMessageBox.question(
            self, self.controller.language.text('Confirm APK installation'),
            self.controller.language.text(
                'Install this APK on the selected Android device? Only install apps you trust.'
            ),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self.start_task(
            'apk',
            lambda: install_android_apk(device['serial'], source),
        )

    def capture_screenshot(self):
        device = self.selected_device()
        if not device or self.loading:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, self.controller.language.text('Save Android screenshot'),
            'android-screenshot.png',
            self.controller.language.text('PNG image (*.png)'),
        )
        if not destination:
            return
        if not destination.lower().endswith('.png'):
            destination += '.png'
        overwrite = os.path.exists(destination)
        if overwrite and QMessageBox.question(
            self, self.controller.language.text('Overwrite file?'),
            self.controller.language.text('Replace the selected local file?'),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self.start_task(
            'screenshot',
            lambda: capture_android_screenshot(
                device['serial'], destination, overwrite=overwrite,
            ),
        )

    def open_entry(self, item, _column):
        entry = item.data(0, Qt.UserRole)
        if entry and entry['is_dir']:
            self.load_directory(posixpath.join(self.remote_path, entry['name']))
        elif entry:
            self.pull_selected()

    def parent_directory(self):
        if self.remote_path != '/':
            self.load_directory(posixpath.dirname(self.remote_path))

    def pull_selected(self):
        device, entry = self.selected_device(), self.selected_entry()
        if not device or not entry or entry['is_dir'] or self.loading:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, self.controller.language.text('Save Android file'), entry['name'],
        )
        if not target:
            return
        if os.path.exists(target) and QMessageBox.question(
            self, self.controller.language.text('Overwrite file?'),
            self.controller.language.text('Replace the selected local file?'),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        remote = posixpath.join(self.remote_path, entry['name'])
        self.start_task(
            'transfer',
            lambda: transfer_android_file(device['serial'], 'pull', target, remote),
        )

    def push_file(self):
        device = self.selected_device()
        if not device or self.loading:
            return
        source, _ = QFileDialog.getOpenFileName(
            self, self.controller.language.text('Select file to send to Android'),
        )
        if source:
            if QMessageBox.question(
                self, self.controller.language.text('Confirm Android upload'),
                self.controller.language.text('A file with this name may be replaced on the phone. Continue?'),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            remote = posixpath.join(self.remote_path, Path(source).name)
            self.start_task(
                'transfer',
                lambda: transfer_android_file(device['serial'], 'push', source, remote),
            )

    def set_reverse(self, enabled):
        device = self.selected_device()
        server = self.controller.server_manager
        if not device or self.loading:
            return
        if enabled and not server.is_running:
            self.status_source = 'Start the HTTP server before enabling USB access.'
            self.status_values = {}
            self.error_detail = ''
            self.retranslate()
            return
        try:
            port = (
                server.httpd.server_address[1] if server.is_running
                else self.reverse_port or int(self.controller.window.line_port.text())
            )
        except ValueError:
            self.status_source = 'Choose a valid HTTP server port before removing USB access.'
            self.status_values = {}
            self.error_detail = ''
            self.retranslate()
            return
        if enabled and server.httpd.server_address[0] not in (
            '', '0.0.0.0', '127.0.0.1', '::', '::1',
        ):
            self.status_source = 'USB reverse access requires the server to listen on localhost or all interfaces.'
            self.status_values = {}
            self.error_detail = ''
            self.retranslate()
            return
        self.start_task(
            'reverse',
            lambda: (enabled, set_android_reverse(device['serial'], port, enabled)),
        )
        if enabled:
            self.reverse_port = port
            scheme = 'https' if server.httpd.app_config.get('use_tls') else 'http'
            self.reverse_url = f'{scheme}://127.0.0.1:{port}'

    def update_actions(self):
        device = self.selected_device()
        entry = self.selected_entry()
        available = device is not None and not self.loading
        session_active = (
            self.scrcpy_process.state() != QProcess.ProcessState.NotRunning
        )
        self.refresh_button.setEnabled(not self.loading and not session_active)
        self.device.setEnabled(not self.loading and not session_active)
        self.path.setEnabled(available)
        self.go_button.setEnabled(available)
        self.parent_button.setEnabled(available and self.remote_path != '/')
        self.pull_button.setEnabled(
            available and bool(entry) and not entry['is_dir'],
        )
        self.push_button.setEnabled(available)
        self.reverse_button.setEnabled(
            available and self.controller.server_manager.is_running,
        )
        self.remove_reverse_button.setEnabled(available)
        self.install_adb_button.setEnabled(
            not self.loading
            and android_adb_install_supported()
            and not android_adb_available()
        )
        self.install_scrcpy_button.setEnabled(
            not self.loading
            and scrcpy_download_supported()
            and not scrcpy_available()
        )
        self.start_scrcpy_button.setEnabled(
            available and not session_active and scrcpy_available()
        )
        self.stop_scrcpy_button.setEnabled(session_active)
        self.clipboard_sync.setEnabled(not self.loading and not session_active)
        self.record_scrcpy.setEnabled(not self.loading and not session_active)
        self.forward_audio.setEnabled(not self.loading and not session_active)
        for control in self.scrcpy_settings:
            enabled = not self.loading and not session_active
            if control in (self.audio_source, self.audio_codec, self.audio_bitrate):
                enabled = enabled and self.forward_audio.isChecked()
            control.setEnabled(enabled)
        for button in self.control_buttons.values():
            button.setEnabled(available)
        self.install_apk_button.setEnabled(available)
        self.screenshot_button.setEnabled(available)

    def retranslate(self):
        language = self.controller.language
        self.setTitle(language.text('Android phone (ADB)'))
        language.apply(self.labels)
        for index, label in enumerate(('Original', '1080p', '720p', '480p')):
            self.resolution.setItemText(index, language.text(label))
        for index, label in enumerate(('Auto', '30 FPS', '60 FPS')):
            self.max_fps.setItemText(index, language.text(label))
        for index, label in enumerate((
            'Device output', 'Playback capture', 'Microphone',
            'Unprocessed microphone', 'Camcorder microphone',
            'Voice recognition microphone', 'Voice communication microphone',
            'Voice call', 'Voice call uplink', 'Voice call downlink',
            'Voice performance',
        )):
            self.audio_source.setItemText(index, language.text(label))
        self.display_orientation.setItemText(0, language.text('Device default'))
        self.status.setText(language.text(self.status_source, **self.status_values))
        if getattr(self, 'error_detail', ''):
            self.status.setText(self.status.text() + '\n' + self.error_detail)
        self.update_actions()


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
