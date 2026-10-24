import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

from src.core.explorer import FileExplorer
from src.core.server import ServerManager
from src.core.temp_links import TemporaryLinks, LinkError, DOWNLOAD_PREFIX


class TestTemporaryLinkStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file = self.root / 'file.txt'
        self.file.write_text('original', encoding='utf-8')
        self.explorer = FileExplorer(self.root)
        self.now = [0.0]
        self.links = TemporaryLinks(clock=lambda: self.now[0])

    def test_expiration_revocation_and_snapshot(self):
        token = self.links.create(self.explorer, self.file, 60)
        self.assertEqual(len(token), 43)
        self.assertEqual(self.links.snapshot()[0]['status'], 'Valid')
        self.now[0] = 60
        with self.assertRaises(LinkError) as error:
            self.links.open_download(token)
        self.assertEqual(error.exception.status, 410)
        self.assertEqual(self.links.snapshot()[0]['status'], 'Expired')
        other = self.links.create(self.explorer, self.file)
        self.assertNotEqual(token, other)
        self.links.revoke(other)
        with self.assertRaises(LinkError):
            self.links.open_download(other)
        self.assertEqual(self.links.snapshot()[0]['status'], 'Revoked')

    def test_file_replacement_invalidates_link(self):
        token = self.links.create(self.explorer, self.file)
        self.file.rename(self.root / 'old.txt')
        self.file.write_text('replacement')
        with self.assertRaises(LinkError) as error:
            self.links.open_download(token)
        self.assertEqual(error.exception.status, 410)
        self.assertEqual(self.links.snapshot()[0]['status'], 'Unavailable')

    def test_outside_root_recovery_data_and_directories_are_rejected(self):
        hidden = self.root / '.serverpy'
        hidden.mkdir()
        (hidden / 'private.txt').write_text('private')
        for path in (self.root, hidden / 'private.txt', self.root / '..' / 'outside.txt'):
            with self.assertRaises(LinkError):
                self.links.create(self.explorer, path)
        for lifetime in (0, True, 8 * 86400):
            with self.assertRaises(LinkError):
                self.links.create(self.explorer, self.file, lifetime)

    def test_password_hash_and_attempt_limit(self):
        password = 'Only-link-password-123'
        token = self.links.create(self.explorer, self.file, password=password)
        self.assertNotIn(password, repr(self.links.records))
        self.assertNotIn('digest', repr(self.links.snapshot()))
        with self.assertRaises(LinkError):
            self.links.open_download(token)
        with patch.object(self.links, 'password_hash', return_value=b'wrong') as password_hash:
            for _ in range(10):
                with self.assertRaises(LinkError) as error:
                    self.links.open_download(token, 'wrong', '192.0.2.1')
                self.assertEqual(error.exception.status, 403)
            with self.assertRaises(LinkError) as error:
                self.links.open_download(token, password, '192.0.2.1')
            self.assertEqual(error.exception.status, 429)
            self.assertEqual(password_hash.call_count, 10)
        self.now[0] = 61
        stream, name, size = self.links.open_download(token, password, '192.0.2.1')
        with stream:
            self.assertEqual(stream.read(), b'original')
        self.assertEqual((name, size), ('file.txt', 8))


class TestTemporaryLinkHTTP(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.file = self.root / 'ação # & 100%20.txt'
        self.file.write_text('selected file', encoding='utf-8')
        (self.root / 'other.txt').write_text('not granted')
        self.server = ServerManager()
        self.start_server()

    def start_server(self):
        ok, message = self.server.start_server('127.0.0.1', 0, str(self.root), render_pages=True,
            allow_mod=True, auth_credentials=('admin', 'server-password'),
            custom_headers={'Cache-Control': 'public', 'Referrer-Policy': 'unsafe-url'},
            cors_config={'origin': '*'})
        self.assertTrue(ok, message)
        self.base = 'http://127.0.0.1:' + str(self.server.httpd.server_address[1])

    def tearDown(self):
        self.server.stop_server()
        self.temp.cleanup()

    def token(self, password=None):
        return self.server.links.create(self.server.httpd.explorer, self.file, password=password)

    def request(self, token, method='GET', password=None, suffix='', headers=None):
        data = None
        headers = dict(headers or {})
        if password is not None:
            data = urllib.parse.urlencode({'password': password}).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        return urllib.request.urlopen(urllib.request.Request(self.base + DOWNLOAD_PREFIX + token + suffix,
            data=data, headers=headers, method=method), timeout=5)

    def assert_error(self, status, token, **options):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(token, **options)
        try:
            self.assertEqual(error.exception.code, status)
            return error.exception.read()
        finally:
            error.exception.close()

    def test_link_grants_only_its_file_without_general_login(self):
        token = self.token()
        with self.request(token) as response:
            self.assertEqual(response.read(), b'selected file')
            self.assertIn('attachment;', response.headers['Content-Disposition'])
            self.assertIn('%C3%A7', response.headers['Content-Disposition'])
            self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
            self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
            self.assertIsNone(response.headers.get('Access-Control-Allow-Origin'))
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(self.base + '/other.txt', timeout=3)
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        self.assert_error(404, token, suffix='/other.txt')
        self.assert_error(404, token, suffix='/api/save', method='POST', password='ignored')
        self.assert_error(405, token, method='DELETE')
        self.assert_error(405, token, method='PUT')
        self.assertTrue(self.file.exists())

    def test_head_provides_metadata_without_file_body(self):
        with self.request(self.token(), method='HEAD') as response:
            self.assertEqual(int(response.headers['Content-Length']), len(b'selected file'))
            self.assertEqual(response.read(), b'')
        with self.request(self.token(password='secret'), method='HEAD') as response:
            self.assertIn('text/html', response.headers['Content-Type'])
            self.assertIsNone(response.headers.get('Content-Disposition'))
            self.assertEqual(response.read(), b'')

    def test_password_form_and_download(self):
        token = self.token(password='link-secret')
        with self.request(token, headers={'Accept-Language': 'pt-BR'}) as response:
            page = response.read().decode()
            self.assertIn('Download protegido', page)
            self.assertIn('method="post"', page)
            self.assertNotIn('link-secret', page)
            self.assertIsNone(response.headers.get('WWW-Authenticate'))
        page = self.assert_error(403, token, method='POST', password='wrong')
        self.assertIn(b'Incorrect link password', page)
        with self.request(token, method='POST', password='link-secret') as response:
            self.assertEqual(response.read(), b'selected file')
            self.assertIsNone(response.headers.get('Set-Cookie'))

    def test_expired_revoked_changed_and_old_session_links_fail(self):
        token = self.token()
        self.server.links.revoke(token)
        self.assert_error(410, token)
        changed = self.token()
        self.file.write_text('changed content')
        self.assert_error(410, changed)
        now = [0.0]
        self.server.links.clock = lambda: now[0]
        expired = self.token()
        now[0] = 3600
        self.assert_error(410, expired)
        old_session = self.token()
        self.server.stop_server()
        self.start_server()
        self.assert_error(404, old_session)

    def test_ip_restrictions_and_rate_limits_still_apply(self):
        token = self.token()
        self.server.httpd.app_config['whitelist'] = ['192.0.2.1']
        self.assert_error(403, token)
        self.server.httpd.app_config.pop('whitelist')
        self.server.httpd.app_config['rate_limit'] = 1
        with self.request(token) as response:
            response.read()
        self.assert_error(429, token)

    def test_tokens_are_redacted_from_logs_and_activity(self):
        token = self.token()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.request(token) as response:
                response.read()
        self.assertNotIn(token, output.getvalue())
        snapshot = repr(self.server.traffic.snapshot())
        self.assertNotIn(token, snapshot)
        self.assertIn('/_download/[link]', snapshot)
