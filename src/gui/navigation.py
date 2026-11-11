"""Main-window tabs and menus, sharing the controller's existing controls."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QLabel, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)
import sys
from .android_panel import AndroidDevicePanel
from .storage import StoragePanel
from .shares import SharedFoldersPanel
from .network_tools import NetworkPanel
from .ssh_panel import SSHPanel
from .activity import ActivityPanel
from .temp_links import TemporaryLinksPanel
from .findport import FindPortPanel
from .transfers import TransfersPanel
from .printing import PrintQueuePanel
from .scanning import ScannerPanel
from .camera import CameraPanel
from .access import FolderAccessPanel
from .profiles import ProfilesPanel
from .action_toolbar import create_action_toolbar
from .vpn_panel import VPNPanel
from vendor.processhunter.core.config import ConfigManager
from vendor.processhunter.core.hunter import ProcessHunter
from vendor.processhunter.core.autostart import WindowsAutostart
from vendor.processhunter.core.logger import setup_app_logger
from vendor.processhunter.ui.main_window import MainWindow as ProcessHunterWindow


class MainNavigation:
    TAB_TITLES = (
        'Server', 'Files', 'Printers', 'Scanners', 'Cameras', 'USB devices',
        'Android', 'Security', 'Settings', 'Network', 'VPN and tunnels', 'ProcessHunter', 'SystemRAM',
    )

    def __init__(self, controller):
        self.controller = controller
        self.window = controller.window
        self.window.resize(980, 760)
        self.window.setMinimumSize(680, 500)
        self.tabs = QTabWidget(self.window)
        self.tabs.setObjectName('main_tabs')
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setDocumentMode(True)
        self.pages = {}
        self.actions = {}
        self.translations = []
        self.tab_actions = []

        # Retain the loaded widgets, signals and QUiLoader attributes.
        original_scroll = self.window.scrollArea
        self.window.centralWidget().layout().replaceWidget(original_scroll, self.tabs)
        for title in self.TAB_TITLES:
            scroll = QScrollArea(self.tabs)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            page = QWidget(scroll)
            page.setObjectName('page_' + title.lower().replace(' ', '_'))
            layout = QVBoxLayout(page)
            layout.setContentsMargins(18, 18, 18, 18)
            layout.setSpacing(16)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, title)
            self.pages[title] = page

        self.move_widget(self.window.groupBox_general, 'Server')
        self.move_widget(self.window.groupBox_files, 'Files')
        self.move_widget(self.window.btn_share_printers, 'Printers')
        self.move_widget(self.window.groupBox_security, 'Security')
        for widget in (self.window.groupBox_misc, controller.advanced_group,
                       self.window.groupBox_database, self.window.groupBox_handlers):
            self.move_widget(widget, 'Settings')

        self.add_description('Server', 'Start the HTTP server and choose the address used to access your files.')
        self.add_description('Files', 'Choose the shared folder and manage network shares.')
        self.add_description('Printers', 'Manage sharing for printers installed on this computer. Other computers may need printer drivers.')
        self.printer_support = self.add_description(
            'Printers', 'Printer sharing requires Windows 10 or 11.',
        )
        self.printer_support.setVisible(not controller.windows_share_supported)
        self.print_queue = PrintQueuePanel(controller, self.pages['Printers'])
        self.pages['Printers'].layout().addWidget(self.print_queue)
        self.scanners = ScannerPanel(controller, self.pages['Scanners'])
        self.pages['Scanners'].layout().addWidget(self.scanners)

        self.pending_buttons = []
        self.cameras = CameraPanel(controller, self.pages['Cameras'])
        self.pages['Cameras'].layout().addWidget(self.cameras)
        self.access = FolderAccessPanel(controller, self.pages['Security'])
        self.pages['Security'].layout().addWidget(self.access)
        self.profiles = ProfilesPanel(controller, self.pages['Settings'])
        self.pages['Settings'].layout().insertWidget(0, self.profiles)

        self.storage = StoragePanel(controller, self.pages['USB devices'])
        self.pages['USB devices'].layout().addWidget(self.storage)
        self.android = AndroidDevicePanel(controller, self.pages['Android'])
        self.pages['Android'].layout().addWidget(self.android)
        self.file_tabs = QTabWidget(self.pages['Files'])
        self.shared_folders = SharedFoldersPanel(controller, self.file_tabs)
        self.links = TemporaryLinksPanel(controller, self.file_tabs)
        self.file_tabs.addTab(self.shared_folders, 'HTTP folders')
        self.file_tabs.addTab(self.links, 'Temporary links')
        self.pages['Files'].layout().addWidget(self.file_tabs)
        self.network_tabs = QTabWidget(self.pages['Network'])
        self.activity = ActivityPanel(controller, self.network_tabs)
        self.network = NetworkPanel(controller, self.network_tabs)
        self.ssh = SSHPanel(controller, self.network_tabs)
        self.network_tabs.addTab(self.activity, 'Activity')
        self.network_tabs.addTab(self.network, 'Diagnostics')
        self.network_tabs.addTab(self.ssh, 'SSH')
        self.findport = FindPortPanel(controller, self.network_tabs)
        self.network_tabs.addTab(self.findport, 'FindPort')
        self.transfers = TransfersPanel(controller, self.network_tabs)
        self.network_tabs.addTab(self.transfers, 'Transfers')
        for panel in (self.activity, self.network, self.ssh):
            panel.layout().setContentsMargins(8, 8, 8, 8)
        self.pages['Network'].layout().addWidget(self.network_tabs)
        self.vpn = VPNPanel(controller, self.pages['VPN and tunnels'])
        self.pages['VPN and tunnels'].layout().addWidget(self.vpn)
        self.process_hunter = ProcessHunterWindow(
            config_manager=controller.processhunter_config,
            hunter=controller.process_hunter,
            autostart=WindowsAutostart(app_name='ProcessHunter'),
            logger=controller.processhunter_logger,
            embedded=True,
            parent=self.pages['ProcessHunter'],
        )
        self.pages['ProcessHunter'].layout().addWidget(self.process_hunter, 1)
        self.systemram = None
        if sys.platform == 'win32':
            from vendor.systemram.gui.main_window import MainWindow as SystemRAMWindow
            self.systemram = SystemRAMWindow(embedded=True, parent=self.pages['SystemRAM'])
            self.pages['SystemRAM'].layout().addWidget(self.systemram, 1)
        else:
            support = QLabel(
                'SystemRAM requires Windows 10 or 11. / SystemRAM requer Windows 10 ou 11.',
                self.pages['SystemRAM'],
            )
            support.setWordWrap(True)
            self.pages['SystemRAM'].layout().addWidget(support)
        self.tabs.currentChanged.connect(self.load_tab)

        for title, page in self.pages.items():
            if title not in ('ProcessHunter', 'SystemRAM'):
                page.layout().addStretch()
        # All controls have moved out of the original scroll container.
        original_scroll.hide()
        original_scroll.deleteLater()
        self.setup_menus()
        self.toolbar = create_action_toolbar(self.window, self.actions)

    def move_widget(self, widget, title):
        parent = widget.parentWidget()
        if parent and parent.layout():
            parent.layout().removeWidget(widget)
        self.pages[title].layout().addWidget(widget)

    def load_tab(self, index):
        title = self.TAB_TITLES[index]
        if title == 'USB devices' and not self.storage.loaded:
            self.storage.refresh()
        elif title == 'Android' and not self.android.devices_loaded:
            self.android.refresh_devices()
        elif title == 'VPN and tunnels' and not self.vpn.loaded:
            self.vpn.refresh()

    def add_description(self, title, source):
        label = QLabel(source, self.pages[title])
        label.setWordWrap(True)
        label.setStyleSheet('color: #b8c1cc;')
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.pages[title].layout().insertWidget(0, label)
        return label

    def add_action(self, menu, key, source, callback, shortcut=None):
        action = QAction(source, self.window)
        action.setObjectName('action_' + key)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(lambda checked=False: callback())
        menu.addAction(action)
        self.actions[key] = action
        self.translations.append((action, 'text', source))
        return action

    def setup_menus(self):
        controller = self.controller
        menu_bar = self.window.menuBar()
        self.menus = {}
        for title in ('Application', 'Server', 'Navigate', 'Language', 'Help'):
            menu = menu_bar.addMenu(title)
            self.menus[title] = menu
            self.translations.append((menu, 'title', title))

        self.add_action(self.menus['Application'], 'logs', 'Server Logs', lambda: controller.log_window.show(), 'Ctrl+L')
        self.menus['Application'].addSeparator()
        self.add_action(self.menus['Application'], 'exit', 'Exit', self.window.close, 'Ctrl+Q')

        server = self.menus['Server']
        self.add_action(server, 'start', 'Start server', controller.window.btn_start.click, 'F5')
        self.add_action(server, 'stop', 'Stop server', controller.window.btn_start.click, 'Shift+F5')
        server.addSeparator()
        self.add_action(server, 'open', 'Open in browser', controller.open_url_button.click, 'Ctrl+O')
        self.add_action(server, 'copy', 'Copy URL', controller.copy_url_button.click)
        self.add_action(server, 'qr', 'Access by QR Code', controller.qr_button.click)
        server.aboutToShow.connect(self.update_server_actions)
        controller.window.btn_start.clicked.connect(self.update_server_actions)

        for index, title in enumerate(self.TAB_TITLES):
            action = self.add_action(
                self.menus['Navigate'], 'tab_' + str(index), title,
                lambda index=index: self.tabs.setCurrentIndex(index), 'Alt+' + str(index + 1) if index < 9 else None,
            )
            action.setCheckable(True)
            self.tab_actions.append(action)
        self.tab_group = QActionGroup(self.window)
        for action in self.tab_actions:
            self.tab_group.addAction(action)
        self.tabs.currentChanged.connect(self.update_tab_actions)
        self.update_tab_actions(0)

        self.language_group = QActionGroup(self.window)
        for code, label in (('en', 'English'), ('pt', 'Português')):
            action = self.add_action(
                self.menus['Language'], 'language_' + code, label,
                lambda code=code: controller.change_language(code),
            )
            action.setCheckable(True)
            self.language_group.addAction(action)
        self.add_action(self.menus['Help'], 'about', 'About', controller.show_about, 'F1')

    def update_tab_actions(self, index):
        self.tab_actions[index].setChecked(True)

    def update_server_actions(self):
        controller = self.controller
        running = controller.server_manager.is_running
        self.actions['start'].setEnabled(not running and controller.window.btn_start.isEnabled())
        self.actions['stop'].setEnabled(running)
        self.actions['open'].setEnabled(controller.open_url_button.isEnabled())
        self.actions['copy'].setEnabled(controller.copy_url_button.isEnabled())
        self.storage.update_actions()
        self.android.update_actions()
        self.shared_folders.update_actions()
        self.actions['qr'].setEnabled(running and bool(controller.access_combo.currentData()))
        self.activity.refresh()
        self.links.refresh()
        self.cameras.update_actions()
        self.access.update_actions()
        self.profiles.update_actions()

    def retranslate(self):
        language = self.controller.language
        self.toolbar.setWindowTitle(language.text('Quick actions'))
        self.toolbar.setAccessibleName(language.text('Quick actions'))
        language.apply(self.translations)
        for index, source in enumerate(self.TAB_TITLES):
            self.tabs.setTabText(index, language.text(source))
        for code in ('en', 'pt'):
            self.actions['language_' + code].setChecked(language.code == code)
        self.update_server_actions()
        self.storage.retranslate()
        self.android.retranslate()
        self.print_queue.retranslate()
        self.scanners.retranslate()
        self.cameras.retranslate()
        self.access.retranslate()
        self.profiles.retranslate()
        self.shared_folders.reload()
        self.network.retranslate()
        self.vpn.retranslate()
        # ProcessHunter keeps its native Portuguese controls and persisted configuration.
        self.activity.retranslate()
        self.ssh.retranslate()
        self.network_tabs.setTabText(0, language.text('Activity'))
        self.network_tabs.setTabText(1, language.text('Diagnostics'))
        self.network_tabs.setTabText(2, language.text('SSH'))
        self.findport.retranslate()
        self.transfers.retranslate()
        self.network_tabs.setTabText(4, language.text('Transfers'))
        self.links.retranslate()
        self.file_tabs.setTabText(0, language.text('HTTP folders'))
        self.file_tabs.setTabText(1, language.text('Temporary links'))
