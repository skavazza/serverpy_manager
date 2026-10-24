import base64
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from src.core.server import ServerManager
from src.core.shares import validate_shared_folders
from src.core.diagnostics import diagnose_endpoint
from src.gui.network_tools import QRCodeDialog, qr_image
from src.gui.i18n import InterfaceLanguage


class TestSharedHTTPFolders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        for name in ('main', 'docs', 'readonly'):
            (cls.root / name).mkdir()
            (cls.root / name / 'hello.txt').write_text(name, encoding='utf-8')
        (cls.root / 'docs' / 'sub').mkdir()
        (cls.root / 'docs' / '.serverpy').mkdir()
        (cls.root / 'docs' / '.serverpy' / 'private.txt').write_text('private')
        cls.server = ServerManager()
        cls.folders = [{'name': 'docs', 'path': str(cls.root / 'docs'), 'writable': True},
                       {'name': 'readonly', 'path': str(cls.root / 'readonly'), 'writable': False}]
        ok, message = cls.server.start_server('127.0.0.1', 0, str(cls.root / 'main'),
            shared_folders=cls.folders, render_pages=True, allow_mod=True,
            auth_credentials=('user', 'password'))
        assert ok, message
        cls.url = 'http://127.0.0.1:' + str(cls.server.httpd.server_address[1])
        cls.auth = 'Basic ' + base64.b64encode(b'user:password').decode()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop_server()
        cls.temp.cleanup()

    def request(self, path, method='GET', payload=None, auth=True):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {'Authorization': self.auth} if auth else {}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        return urllib.request.urlopen(urllib.request.Request(self.url + path, data=data, headers=headers, method=method), timeout=3)

    def test_named_roots_serve_their_own_files_and_share_authentication(self):
        for prefix, content in (('', 'main'), ('/_shares/docs', 'docs'), ('/_shares/readonly', 'readonly')):
            with self.request(prefix + '/hello.txt') as response:
                self.assertEqual(response.read().decode(), content)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/_shares/docs/hello.txt', auth=False)
        self.assertEqual(error.exception.code, 401)
        error.exception.close()

    def test_page_links_prefix_and_readonly_permission(self):
        with self.request('/_shares/readonly/') as response:
            page = response.read().decode()
        self.assertIn('data-url-prefix="/_shares/readonly"', page)
        self.assertIn('data-allow-mod="false"', page)
        self.assertIn('href="/_shares/docs/"', page)
        self.assertNotIn('{shares_nav}', page)
        self.assertNotIn('{url_prefix}', page)
        with self.request('/_shares/docs') as response:
            self.assertEqual(response.url, self.url + '/_shares/docs/')
        with self.request('/_shares/docs/sub') as response:
            self.assertEqual(response.url, self.url + '/_shares/docs/sub/')

    def test_mutations_and_recovery_remain_in_the_selected_root(self):
        with self.request('/_shares/docs/api/save', 'POST', {'path': '/new.txt', 'content': 'new'}):
            pass
        self.assertTrue((self.root / 'docs' / 'new.txt').is_file())
        self.assertFalse((self.root / 'main' / 'new.txt').exists())
        with self.request('/_shares/docs/new.txt', 'DELETE'):
            pass
        with self.request('/_shares/docs/api/trash') as response:
            item = next(item for item in json.load(response)['items'] if item['name'] == 'new.txt')
        with self.request('/api/trash') as response:
            self.assertEqual(json.load(response)['items'], [])
        with self.request('/_shares/docs/api/restore', 'POST', {'id': item['id']}):
            pass
        self.assertEqual((self.root / 'docs' / 'new.txt').read_text(), 'new')

    def test_readonly_blocks_all_mutation_methods_and_intents(self):
        for path, method, payload in (
            ('/hello.txt', 'DELETE', None), ('/upload.txt', 'PUT', {}),
            ('/api/save', 'POST', {'path': '/hello.txt', 'content': 'changed'}),
            ('/api/intent', 'POST', {'command': 'ignored'}),
        ):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request('/_shares/readonly' + path, method, payload)
            self.assertEqual(error.exception.code, 405)
            error.exception.close()
        self.assertEqual((self.root / 'readonly' / 'hello.txt').read_text(), 'readonly')

    def test_traversal_unknown_mounts_and_recovery_data_are_blocked(self):
        for path, status in (
            ('/_shares/docs/../main/hello.txt', 403),
            ('/_shares/docs/%2e%2e/main/hello.txt', 403),
            ('/_shares/docs/.serverpy/private.txt', 403),
            ('/_shares/missing/hello.txt', 404),
        ):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(path)
            self.assertEqual(error.exception.code, status)
            error.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/_shares/docs/api/save', 'POST', {'path': '../main/leak.txt', 'content': 'bad'})
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

    def test_search_tree_and_head_are_scoped(self):
        with self.request('/_shares/docs/api/search?q=hello') as response:
            self.assertEqual(json.load(response)['items'][0]['path'], '/hello.txt')
        with self.request('/_shares/docs/api/folders?path=/') as response:
            folders = json.load(response)['folders']
        self.assertIn({'name': 'sub', 'path': '/sub/'}, folders)
        self.assertFalse(any(item['name'] == '.serverpy' for item in folders))
        with self.request('/_shares/docs/hello.txt', 'HEAD') as response:
            self.assertEqual(response.read(), b'')
            self.assertEqual(int(response.headers['Content-Length']), 4)

    def test_disconnected_folder_is_unavailable_and_is_not_recreated(self):
        source = self.root / 'readonly'
        moved = self.root / 'unplugged'
        source.rename(moved)
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request('/_shares/readonly/new.txt', 'PUT', {})
            self.assertEqual(error.exception.code, 503)
            error.exception.close()
            self.assertFalse(source.exists())
        finally:
            moved.rename(source)

    def test_global_readonly_also_limits_writable_additional_folders(self):
        server = ServerManager()
        ok, message = server.start_server('127.0.0.1', 0, str(self.root / 'main'),
            shared_folders=self.folders, allow_mod=False, render_pages=True)
        self.assertTrue(ok, message)
        try:
            url = 'http://127.0.0.1:' + str(server.httpd.server_address[1]) + '/_shares/docs/hello.txt'
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(url, method='DELETE'), timeout=3)
            self.assertEqual(error.exception.code, 405)
            error.exception.close()
        finally:
            server.stop_server()


class TestNetworkTools(unittest.TestCase):
    def test_validation_prevents_duplicate_names_and_missing_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            item = {'name': 'docs', 'path': folder}
            for items in ([item, dict(item, name='DOCS')], [dict(item, name='../bad')],
                          [dict(item, path=os.path.join(folder, 'missing'))]):
                with self.assertRaises(ValueError):
                    validate_shared_folders(items)
        # Remember disconnected devices in preferences, but reject them at start.
        self.assertEqual(validate_shared_folders([item], check_paths=False)[0]['name'], 'docs')

    def test_live_diagnostics_recognizes_authenticated_server(self):
        with tempfile.TemporaryDirectory() as folder:
            server = ServerManager()
            ok, message = server.start_server('127.0.0.1', 0, folder, auth_credentials=('user', 'password'))
            self.assertTrue(ok, message)
            try:
                rows = diagnose_endpoint('127.0.0.1', server.httpd.server_address[1])
                self.assertEqual(rows[0][1], 'OK')
                self.assertEqual(rows[1][1], 'OK')
                self.assertEqual(rows[2][1], 'Reachable')
                self.assertIn('401', rows[2][2])
            finally:
                server.stop_server()

    def test_https_diagnostic_detects_local_plain_http_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            server = ServerManager()
            ok, message = server.start_server('127.0.0.1', 0, folder, render_pages=True)
            self.assertTrue(ok, message)
            try:
                rows = diagnose_endpoint(
                    '127.0.0.1', server.httpd.server_address[1], use_tls=True,
                )
                self.assertEqual(rows[2][0:2], ('HTTPS response', 'Failed'))
                self.assertEqual(rows[3][0:2], ('HTTP fallback', 'Reachable'))
                self.assertIn('200', rows[3][2])
                self.assertEqual(rows[4][0:2], ('Protocol guidance', 'Use HTTP'))
                self.assertIn('Disable Use HTTPS', rows[4][2])
                self.assertIn('Cloudflare', rows[4][2])
            finally:
                server.stop_server()

    def test_dns_failure_and_invalid_inputs(self):
        with patch('src.core.diagnostics.socket.getaddrinfo', side_effect=socket.gaierror('not found')):
            self.assertEqual(diagnose_endpoint('missing.invalid', 80)[0][1], 'Failed')
        for host, port in (('http://localhost', 80), ('localhost', 0), ('', 80)):
            with self.assertRaises(ValueError):
                diagnose_endpoint(host, port)

    def test_qr_image_can_be_exported_and_loopback_is_explained(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            image = qr_image('http://192.168.1.10:8080/_shares/docs/')
            self.assertFalse(image.isNull())
            self.assertEqual(image.pixelColor(0, 0).name(), '#ffffff')
            self.assertTrue(image.save(os.path.join(directory, 'code.png'), 'PNG'))
        from PySide6.QtWidgets import QLabel
        dialog = QRCodeDialog('http://127.0.0.1:8080/', None, InterfaceLanguage('pt'))
        try:
            self.assertTrue(any('apenas neste computador' in label.text() for label in dialog.findChildren(QLabel)))
        finally:
            dialog.close()
