import base64
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from src.core.server import ServerManager


class TestPWA(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='serverpy_pwa_')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'nested').mkdir()
        self.manager = ServerManager()
        ok, message = self.manager.start_server('127.0.0.1', 0, temporary.name,
                                                render_pages=True, auth_credentials=('user', 'pass'))
        self.assertTrue(ok, message)
        self.addCleanup(self.manager.stop_server)
        self.url = 'http://127.0.0.1:' + str(self.manager.httpd.server_address[1])
        self.auth = {'Authorization': 'Basic ' + base64.b64encode(b'user:pass').decode()}

    def request(self, path, method='GET', authenticated=True):
        request = urllib.request.Request(self.url + path, method=method,
                                         headers=self.auth if authenticated else {})
        return urllib.request.urlopen(request, timeout=5)

    def test_manifest_and_nested_listing_use_absolute_routes(self):
        for route in ('/', '/nested/'):
            with self.request(route) as response:
                self.assertIn(b'href="/_serverpy/pwa/manifest.webmanifest"', response.read())
        with self.request('/_serverpy/pwa/manifest.webmanifest?version=1') as response:
            self.assertIn('application/manifest+json', response.headers['Content-Type'])
            manifest = json.load(response)
        self.assertEqual(manifest['start_url'], '/')
        self.assertEqual(manifest['scope'], '/')
        self.assertEqual(manifest['display'], 'standalone')
        for icon in manifest['icons']:
            with self.request(icon['src']) as response:
                data = response.read()
                self.assertEqual(response.headers['Content-Type'], 'image/png')
                self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
                dimension = int.from_bytes(data[16:20], 'big')
                self.assertEqual(icon['sizes'], f'{dimension}x{dimension}')

    def test_worker_scope_head_and_bundled_assets(self):
        for name, mime in [('sw.js', 'text/javascript'), ('pwa.js', 'text/javascript'),
                           ('offline.html', 'text/html')]:
            with self.request('/_serverpy/pwa/' + name) as response:
                content = response.read()
                self.assertIn(mime, response.headers['Content-Type'])
                length = response.headers['Content-Length']
                if name == 'sw.js':
                    self.assertEqual(response.headers['Service-Worker-Allowed'], '/')
                    self.assertEqual(response.headers['Cache-Control'], 'no-cache')
            with self.request('/_serverpy/pwa/' + name, method='HEAD') as response:
                self.assertEqual(response.read(), b'')
                self.assertEqual(response.headers['Content-Length'], length)
            self.assertTrue(content)
        # Never serve a same-named file from the user's shared folder.
        (self.root / '_serverpy' / 'pwa').mkdir(parents=True)
        (self.root / '_serverpy' / 'pwa' / 'sw.js').write_text('untrusted user file')
        with self.request('/_serverpy/pwa/sw.js') as response:
            self.assertNotIn(b'untrusted user file', response.read())

    def test_assets_follow_auth_and_render_permissions(self):
        for route in ('manifest.webmanifest', 'sw.js', 'offline.html', 'icon-192.png'):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request('/_serverpy/pwa/' + route, authenticated=False)
            self.assertEqual(caught.exception.code, 401)
            caught.exception.close()
        self.manager.httpd.app_config['render_pages'] = False
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/_serverpy/pwa/sw.js')
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_ping_is_live_authenticated_and_allowed_in_readonly_mode(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/api/ping', authenticated=False)
        self.assertEqual(caught.exception.code, 401)
        caught.exception.close()
        self.manager.httpd.app_config['allow_mod'] = False
        with self.request('/api/ping') as response:
            self.assertEqual(json.load(response), {'ok': True})
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.manager.httpd.app_config['render_pages'] = False
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/api/ping')
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_unknown_asset_does_not_expose_template_files(self):
        for path in ('unknown.js', '../web_interface.html', '%2e%2e/web_interface.html'):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request('/_serverpy/pwa/' + path)
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()
