"""Save and apply validated server configuration profiles while stopped."""

import json
import os

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QInputDialog, QMessageBox, QStyle

from ..core.profiles import ProfileStore, validate_profile


class ProfilesPanel(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.store = ProfileStore(controller.settings)
        layout = QVBoxLayout(self)
        self.note = QLabel(self)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.names = QComboBox(self)
        layout.addWidget(self.names)
        row = QHBoxLayout()
        self.buttons = {}
        for source, icon, callback in (
            ('Save current as profile', QStyle.SP_DialogSaveButton, self.save_current),
            ('Apply profile', QStyle.SP_DialogApplyButton, self.apply_selected),
            ('Delete profile', QStyle.SP_TrashIcon, self.delete_selected),
        ):
            button = QPushButton(self)
            button.setIcon(self.style().standardIcon(icon))
            button.clicked.connect(callback)
            row.addWidget(button)
            self.buttons[source] = button
        layout.addLayout(row)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.names.currentIndexChanged.connect(self.update_actions)
        self.retranslate()
        self.reload()

    def reload(self, selected=None):
        selected = selected or self.names.currentText()
        self.names.clear()
        try:
            self.names.addItems(sorted(self.store.read(), key=str.casefold))
            index = self.names.findText(selected)
            if index >= 0:
                self.names.setCurrentIndex(index)
        except ValueError as error:
            self.status.setText(self.controller.language.text(str(error)))
        self.update_actions()

    def snapshot(self):
        self.controller.save_server_preferences()
        settings = self.controller.settings
        panel = self.controller.navigation.cameras
        return {'root_folder': os.path.abspath(self.controller.window.line_root_folder.text().strip()), 'port': self.controller.window.line_port.text().strip(),
                'interface': self.controller.window.combo_interface.currentText().split()[0], 'options': json.loads(settings.value('server/options', '{}')),
                'camera': {'fps': panel.fps.value(), 'quality': panel.quality.value(), 'resolution_width': panel.resolution.currentData()[0]}}

    def save_current(self):
        if self.controller.server_manager.is_running:
            return
        text = self.controller.language.text
        name, ok = QInputDialog.getText(self, text('Configuration profiles'), text('Profile name:'), text=self.names.currentText())
        if not ok:
            return
        try:
            name = self.store.name(name)
            if name in self.store.read() and QMessageBox.question(self, text('Configuration profiles'), text('Replace the existing profile?'), QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            self.store.save(name, self.snapshot())
            self.reload(name)
            self.status.setText(text('Profile saved.'))
        except (ValueError, TypeError) as error:
            self.status.setText(text(str(error)))

    def apply_profile(self, name):
        if self.controller.server_manager.is_running:
            raise ValueError('Stop the server before applying a profile.')
        profile = validate_profile(self.store.read()[name], check_paths=True)
        interfaces = [self.controller.window.combo_interface.itemText(index).split()[0] for index in range(self.controller.window.combo_interface.count())]
        if profile['interface'] not in interfaces:
            raise ValueError('The profile network interface is unavailable.')
        # All schema and availability checks complete before changing any controls.
        self.controller.restore_server_preferences(profile)
        self.controller.window.line_username.clear()
        self.controller.window.line_password.clear()
        camera = self.controller.navigation.cameras
        for widget in (camera.fps, camera.quality, camera.resolution):
            widget.blockSignals(True)
        camera.fps.setValue(profile['camera']['fps'])
        camera.quality.setValue(profile['camera']['quality'])
        from .camera import RESOLUTIONS
        camera.resolution.setCurrentIndex([width for width, _ in RESOLUTIONS].index(profile['camera']['resolution_width']))
        for widget in (camera.fps, camera.quality, camera.resolution):
            widget.blockSignals(False)
        camera.change_fps(camera.fps.value())
        camera.change_image_settings()
        self.controller.save_server_preferences()
        self.controller.refresh_language()
        self.status.setText(self.controller.language.text('Profile applied. Re-enter the general login if enabled. The server remains stopped.'))

    def apply_selected(self):
        if not self.names.currentText():
            return
        try:
            self.apply_profile(self.names.currentText())
        except (ValueError, KeyError, TypeError) as error:
            self.status.setText(self.controller.language.text(str(error)))

    def delete_selected(self):
        if self.controller.server_manager.is_running or not self.names.currentText():
            return
        text = self.controller.language.text
        if QMessageBox.question(self, text('Configuration profiles'), text('Delete this configuration profile?'), QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.store.delete(self.names.currentText())
            self.reload()
            self.status.setText(text('Profile deleted.'))
        except (ValueError, KeyError) as error:
            self.status.setText(text(str(error)))

    def update_actions(self):
        stopped = not self.controller.server_manager.is_running
        self.names.setEnabled(stopped)
        for source, button in self.buttons.items():
            button.setEnabled(stopped and (source == 'Save current as profile' or bool(self.names.currentText())))

    def retranslate(self):
        text = self.controller.language.text
        self.setTitle(text('Configuration profiles'))
        self.note.setText(text('Save folders, port, network, access rules and camera settings. Applying a profile requires a stopped server. General login credentials are excluded; folder accounts contain password hashes.'))
        self.names.setAccessibleName(text('Configuration profiles'))
        for source, button in self.buttons.items():
            button.setText(text(source))
        self.update_actions()
