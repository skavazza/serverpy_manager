import base64
import copy
import http.client
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from src.core.access import hash_password, verify_password, validate_users, PERMISSIONS
from src.core.profiles import ProfileStore, validate_profile
from src.core.server import ServerManager
from src.gui.access import FolderUserDialog
from src.gui.controller import AppController


class TestFolderAccess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = hash_password('folder-secret')

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.main = Path(self.scratch.name) / 'main'
        self.extra = Path(self.scratch.name) / 'extra'
        for root in (self.main, self.extra):
            root.mkdir()
            (root / 'old.txt').write_text('original', encoding='utf-8')
            (root / 'New Folder').mkdir()
        self.server = ServerManager()
        self.addCleanup(self.server.stop_server)

    def start(self, grants, **options):
        config = dict(allow_mod=True, render_pages=True,
            shared_folders=[{'name': 'extra', 'path': str(self.extra), 'writable': True}],
            folder_users_enabled=True,
            folder_users=[{'name': 'reader', 'password': self.password, 'grants': grants}])
        config.update(options)
        ok, message = self.server.start_server('127.0.0.1', 0, str(self.main), **config)
        self.assertTrue(ok, message)
        self.port = self.server.httpd.server_address[1]

    def request(self, path, method='GET', payload=None, user='reader', password='folder-secret', raw=None):
        headers = {}
        if user is not None:
            headers['Authorization'] = 'Basic ' + base64.b64encode((user + ':' + password).encode()).decode()
        body = json.dumps(payload).encode() if payload is not None else raw
        if body is not None:
            headers['Content-Length'] = str(len(body))
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_password_hash_and_validation(self):
        self.assertTrue(verify_password('folder-secret', self.password))
        self.assertFalse(verify_password('wrong', self.password))
        self.assertNotEqual(hash_password('folder-secret'), self.password)
        self.assertNotIn('folder-secret', json.dumps(self.password))
        with self.assertRaises(ValueError):
            hash_password('short')
        with self.assertRaises(ValueError):
            validate_users([{'name': 'bad:name', 'password': self.password, 'grants': {}}])

    def test_authentication_and_default_deny(self):
        self.start({'extra': ['view', 'download']})
        self.assertEqual(self.request('/_shares/extra/', user=None)[0], 401)
        self.assertEqual(self.request('/_shares/extra/', password='wrong')[0], 401)
        self.assertEqual(self.request('/')[0], 403)
        self.assertEqual(self.request('/old.txt')[0], 403)
        self.assertEqual(self.request('/_shares/extra/old.txt'), (200, b'original'))
        page = self.request('/_shares/extra/')[1].decode()
        self.assertNotIn('href="/" class="tool-btn"', page)
        self.assertIn('data-permissions="[&quot;download&quot;, &quot;view&quot;]"', page)
        self.assertEqual(self.request('/_shares/extra/old.txt', 'PUT', raw=b'attack')[0], 403)
        self.assertEqual(self.request('/_camera/')[0], 403)
        self.assertEqual(self.request('/api/intent', 'POST', {'command': 'anything'})[0], 403)

    def test_view_is_separate_from_download_and_handles_encoded_directories(self):
        self.start({'/': ['view']})
        self.assertEqual(self.request('/')[0], 200)
        self.assertEqual(self.request('/New%20Folder/')[0], 200)
        self.assertEqual(self.request('/api/search?q=old')[0], 200)
        for path in ('/old.txt', '/api/read?path=/old.txt', '/api/zip?path=/'):
            self.assertEqual(self.request(path)[0], 403)
            self.assertEqual(self.request(path, 'HEAD')[0], 403)
        self.assertEqual(self.request('/api/trash')[0], 403)
        self.assertEqual(self.request('/old.txt', 'DELETE')[0], 403)

    def test_upload_cannot_overwrite_edit_or_delete(self):
        self.start({'/': ['view', 'upload']})
        self.assertEqual(self.request('/new.txt', 'PUT', raw=b'new')[0], 201)
        self.assertEqual((self.main / 'new.txt').read_bytes(), b'new')
        self.assertEqual(self.request('/old.txt', 'PUT', raw=b'changed')[0], 403)
        self.assertEqual(self.request('/api/save', 'POST', {'path': '/old.txt', 'content': 'changed'})[0], 403)
        self.assertEqual(self.request('/api/save', 'POST', {'path': '/created.txt', 'content': 'new'})[0], 200)
        self.assertEqual(self.request('/api/mkdir', 'POST', {'path': '/created'})[0], 201)
        self.assertEqual(self.request('/api/rename', 'POST', {'old': '/old.txt', 'new': '/renamed.txt'})[0], 403)
        self.assertEqual(self.request('/old.txt', 'DELETE')[0], 403)
        self.assertEqual((self.main / 'old.txt').read_text(), 'original')

    def test_edit_and_delete_permissions_are_independent(self):
        self.start({'/': ['view', 'edit']})
        self.assertEqual(self.request('/old.txt', 'PUT', raw=b'edited')[0], 201)
        self.assertEqual(self.request('/new.txt', 'PUT', raw=b'new')[0], 403)
        self.assertEqual(self.request('/api/save', 'POST', {'path': '/old.txt', 'content': 'saved'})[0], 200)
        self.assertEqual(self.request('/old.txt', 'DELETE')[0], 403)
        self.server.httpd.app_config['folder_users'][0]['grants']['/'] = ['view', 'delete']
        self.assertEqual(self.request('/old.txt', 'DELETE')[0], 204)
        self.assertFalse((self.main / 'old.txt').exists())
        status, body = self.request('/api/trash')
        self.assertEqual(status, 200)
        item = json.loads(body)['items'][0]
        self.assertEqual(self.request('/api/restore', 'POST', {'id': item['id']})[0], 403)

    def test_full_grants_recovery_copy_and_global_write_switch(self):
        self.start({'extra': list(PERMISSIONS)}, auth_credentials=('admin', 'admin-secret'))
        prefix = '/_shares/extra'
        self.assertEqual(self.request(prefix + '/api/copy', 'POST', {'src': '/old.txt', 'dst': '/copy.txt'})[0], 200)
        self.assertEqual(self.request(prefix + '/api/rename', 'POST', {'old': '/copy.txt', 'new': '/renamed.txt'})[0], 200)
        self.assertEqual(self.request(prefix + '/renamed.txt', 'DELETE')[0], 204)
        items = json.loads(self.request(prefix + '/api/trash')[1])['items']
        self.assertEqual(self.request(prefix + '/api/restore', 'POST', {'id': items[0]['id']})[0], 200)
        self.assertEqual(self.request('/', user='admin', password='admin-secret')[0], 200)
        self.assertEqual(self.request('/_camera/', user='admin', password='admin-secret')[0], 200)
        self.server.httpd.app_config['allow_mod'] = False
        self.assertEqual(self.request(prefix + '/new.txt', 'PUT', raw=b'no')[0], 405)

    def test_overlapping_roots_and_invalid_accounts_are_rejected(self):
        config = dict(folder_users_enabled=True, folder_users=[{'name': 'reader', 'password': self.password, 'grants': {'/': ['view']}}])
        ok, message = self.server.start_server('127.0.0.1', 0, self.scratch.name,
            shared_folders=[{'name': 'nested', 'path': str(self.extra), 'writable': True}], **config)
        self.assertFalse(ok)
        self.assertIn('must not overlap', message)
        ok, _ = self.server.start_server('127.0.0.1', 0, str(self.main), folder_users_enabled=True, folder_users=[])
        self.assertFalse(ok)


class TestConfigurationProfiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / 'main'
        self.extra = Path(self.scratch.name) / 'extra'
        self.root.mkdir()
        self.extra.mkdir()
        self.settings = QSettings(str(Path(self.scratch.name) / 'preferences.ini'), QSettings.IniFormat)
        self.profile = {'root_folder': str(self.root), 'port': '0', 'interface': '127.0.0.1',
            'options': {'shared_folders': [], 'chk_allow_mod': True},
            'camera': {'fps': 15, 'quality': 80, 'resolution_width': 1280}}

    def controller(self):
        import sys
        streams = sys.stdout, sys.stderr
        with patch('src.gui.controller.QSettings', return_value=self.settings), patch('src.gui.controller.StartupRegistration') as startup:
            startup.return_value.supported = False
            controller = AppController()
        sys.stdout, sys.stderr = streams
        controller.window.line_root_folder.setText(str(self.root))
        self.addCleanup(controller.log_window.close)
        self.addCleanup(controller.window.close)
        self.addCleanup(controller.schedule_timer.stop)
        self.addCleanup(controller.server_manager.stop_server)
        return controller

    def test_store_roundtrip_delete_corruption_and_no_plaintext_credentials(self):
        store = ProfileStore(self.settings)
        store.save('Rede doméstica', self.profile)
        self.assertEqual(ProfileStore(self.settings).read()['Rede doméstica']['camera']['fps'], 15)
        self.profile['port'] = '9001'
        store.save('Rede doméstica', self.profile)
        self.assertEqual(store.read()['Rede doméstica']['port'], '9001')
        sensitive = copy.deepcopy(self.profile)
        sensitive['options']['password'] = 'plaintext'
        with self.assertRaises(ValueError):
            store.save('Unsafe', sensitive)
        store.delete('Rede doméstica')
        self.assertEqual(store.read(), {})
        self.settings.setValue('profiles/data', 'broken data')
        with self.assertRaises(ValueError):
            store.save('New', self.profile)
        self.assertEqual(self.settings.value('profiles/data'), 'broken data')

    def test_apply_restores_options_camera_and_accounts_without_starting(self):
        controller = self.controller()
        self.profile['options'].update(folder_users_enabled=True,
            folder_users=[{'name': 'beth', 'password': hash_password('beth-secret'), 'grants': {'/': ['view'], 'docs': ['view', 'download']}}],
            shared_folders=[{'name': 'docs', 'path': str(self.extra), 'writable': False}])
        panel = controller.navigation.profiles
        panel.store.save('Trabalho', self.profile)
        controller.window.line_username.setText('admin')
        controller.window.line_password.setText('temporary-password')
        panel.apply_profile('Trabalho')
        self.assertEqual(controller.window.line_port.text(), '0')
        self.assertEqual(controller.navigation.cameras.fps.value(), 15)
        self.assertEqual(controller.navigation.cameras.quality.value(), 80)
        self.assertEqual(controller.navigation.cameras.resolution.currentData(), (1280, 720))
        self.assertTrue(controller.folder_users_enabled)
        self.assertTrue(verify_password('beth-secret', controller.folder_users[0]['password']))
        self.assertEqual(controller.window.line_password.text(), '')
        self.assertEqual(controller.window.line_username.text(), '')
        self.assertFalse(controller.server_manager.is_running)
        self.assertNotIn('temporary-password', self.settings.value('server/options'))

    def test_missing_folder_or_interface_and_running_server_do_not_mutate(self):
        controller = self.controller()
        panel = controller.navigation.profiles
        panel.store.save('Saved', self.profile)
        before = controller.window.line_root_folder.text(), controller.window.line_port.text()
        self.root.rmdir()
        with self.assertRaises(ValueError):
            panel.apply_profile('Saved')
        self.assertEqual(before, (controller.window.line_root_folder.text(), controller.window.line_port.text()))
        self.root.mkdir()
        self.profile['interface'] = '192.0.2.123'
        panel.store.save('Offline network', self.profile)
        with self.assertRaises(ValueError):
            panel.apply_profile('Offline network')
        self.assertEqual(before, (controller.window.line_root_folder.text(), controller.window.line_port.text()))
        controller.server_manager.is_running = True
        try:
            with self.assertRaises(ValueError):
                panel.apply_profile('Saved')
            panel.update_actions()
            self.assertFalse(panel.buttons['Apply profile'].isEnabled())
        finally:
            controller.server_manager.is_running = False

    def test_user_dialog_grants_hash_and_edit_keeps_password(self):
        controller = self.controller()
        controller.shared_folders = [{'name': 'docs', 'path': str(self.extra), 'writable': True}]
        dialog = FolderUserDialog(controller)
        dialog.name.setText('beth')
        dialog.password.setText('beth-secret')
        dialog.table.item(1, 1).setCheckState(Qt.Checked)
        dialog.table.item(1, 2).setCheckState(Qt.Checked)
        dialog.accept()
        self.assertEqual(dialog.result(), 1)
        self.assertEqual(dialog.value['grants']['docs'], ['view', 'download'])
        self.assertTrue(verify_password('beth-secret', dialog.value['password']))
        controller.folder_users = [dialog.value]
        edit = FolderUserDialog(controller, account=dialog.value)
        edit.accept()
        self.assertEqual(edit.value['password'], dialog.value['password'])
        self.assertEqual(edit.password.text(), '')
        dialog.close()
        edit.close()
