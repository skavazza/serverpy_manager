import http.client
import io
import json
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from src.core.server import ServerManager
from src.core.http_limits import HTTPResourceError


class TestHTTPResourceLimits(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        (self.root / 'old.txt').write_bytes(b'original')
        self.server = ServerManager()
        self.addCleanup(self.server.stop_server)

    def start(self, **config):
        ok, message = self.server.start_server('127.0.0.1', 0, str(self.root),
                                              allow_mod=True, render_pages=True, **config)
        self.assertTrue(ok, message)
        self.port = self.server.httpd.server_address[1]

    def request(self, path='/', method='GET', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def raw(self, data, shutdown=False):
        client = socket.create_connection(('127.0.0.1', self.port), timeout=3)
        self.addCleanup(client.close)
        client.sendall(data)
        if shutdown:
            client.shutdown(socket.SHUT_WR)
        return client

    def test_post_limits_apply_before_mutation_and_preserve_existing_file(self):
        self.start(max_post_bytes=64)
        for route in ('save', 'mkdir', 'rename', 'copy', 'move', 'restore', 'undo-move'):
            self.assertEqual(self.request('/api/' + route, 'POST', b'x' * 65)[0], 413)
        self.assertEqual((self.root / 'old.txt').read_bytes(), b'original')
        body = json.dumps({'path': '/new', 'content': 'ok'})
        self.assertEqual(self.request('/api/save', 'POST', body)[0], 200)
        self.assertEqual((self.root / 'new').read_text(), 'ok')

    def test_invalid_framing_and_json_have_client_errors(self):
        self.start()
        cases = [(b'', 411), (b'Content-Length: -1\r\n', 400),
                 (b'Content-Length: 1\r\nContent-Length: 2\r\n', 400),
                 (b'Transfer-Encoding: chunked\r\n', 400)]
        for headers, expected in cases:
            client = self.raw(b'POST /api/save HTTP/1.1\r\nHost: localhost\r\n' + headers + b'\r\n')
            response = http.client.HTTPResponse(client)
            response.begin()
            self.assertEqual(response.status, expected)
            response.read()
        for body in (b'[]', b'null', b'{', b'\xff'):
            self.assertEqual(self.request('/api/save', 'POST', body)[0], 400)

    def test_incomplete_and_stalled_posts_do_not_change_existing_file(self):
        self.start(body_timeout=0.15)
        for shutdown, expected in ((True, 400), (False, 408)):
            client = self.raw(b'POST /api/save HTTP/1.1\r\nHost: localhost\r\nContent-Length: 50\r\n\r\n{', shutdown)
            response = http.client.HTTPResponse(client)
            response.begin()
            self.assertEqual(response.status, expected)
            response.read()
        self.assertEqual((self.root / 'old.txt').read_bytes(), b'original')

    def test_upload_excess_and_timeout_preserve_destination_and_cleanup(self):
        self.start(max_upload_bytes=8, upload_idle_timeout=0.15)
        self.assertEqual(self.request('/old.txt', 'PUT', b'123456789')[0], 413)
        client = self.raw(b'PUT /old.txt HTTP/1.1\r\nHost: localhost\r\nContent-Length: 8\r\n\r\n12')
        response = http.client.HTTPResponse(client)
        response.begin()
        self.assertEqual(response.status, 408)
        response.read()
        self.assertEqual((self.root / 'old.txt').read_bytes(), b'original')
        self.assertEqual(self.request('/new.txt', 'PUT', b'12345678')[0], 201)

    def test_connection_saturation_idle_expiry_and_recovery(self):
        self.start(max_connections=1, request_timeout=0.2)
        self.assertTrue(self.server.httpd.connection_slots.acquire(timeout=1))
        try:
            self.assertEqual(self.request()[0], 503)
        finally:
            self.server.httpd.connection_slots.release()
        idle = self.raw(b'GET / HTTP/1.1\r\n')
        self.assertEqual(idle.recv(4096), b'')
        deadline = time.monotonic() + 2
        while self.request()[0] == 503:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

    def test_rate_history_expires_and_has_a_capacity_bound(self):
        self.start(rate_limit=2, rate_limit_max_ips=1, rate_limit_ttl=1)
        tracker = self.server.httpd.ip_tracker
        from collections import deque
        tracker['old'] = deque([time.monotonic() - 2])
        self.assertEqual(self.request('/old.txt')[0], 200)
        self.assertNotIn('old', tracker)
        self.assertLessEqual(len(tracker), 1)
        tracker.clear()
        tracker['other'] = deque([time.monotonic()])
        self.assertEqual(self.request()[0], 429)
        self.assertEqual(len(tracker), 1)
        tracker.clear()
        self.assertEqual(self.request('/old.txt')[0], 200)

    def test_zip_is_valid_and_excludes_private_state(self):
        self.start()
        (self.root / '.serverpy').mkdir(exist_ok=True)
        (self.root / '.serverpy' / 'secret').write_text('secret')
        (self.root / 'large.bin').write_bytes(b'large file' * 100000)
        status, body = self.request('/api/zip?path=/')
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertEqual(set(archive.namelist()), {'old.txt', 'large.bin'})
            self.assertEqual(archive.read('large.bin'), (self.root / 'large.bin').read_bytes())

    def test_zip_size_entry_timeout_and_busy_limits_recover_and_close_tempfiles(self):
        self.start(zip_max_bytes=4)
        self.assertEqual(self.request('/api/zip?path=/')[0], 413)
        self.server.httpd.app_config.update(zip_max_bytes=1024 * 1024, zip_max_entries=1)
        (self.root / 'second').write_text('two')
        self.assertEqual(self.request('/api/zip?path=/')[0], 413)
        self.server.httpd.app_config['zip_max_entries'] = 100
        with patch('src.core.handlers.build_archive', side_effect=HTTPResourceError(503, 'ZIP generation timed out')):
            self.assertEqual(self.request('/api/zip?path=/')[0], 503)
        self.server.httpd.zip_slot.acquire()
        try:
            self.assertEqual(self.request('/api/zip?path=/')[0], 503)
        finally:
            self.server.httpd.zip_slot.release()
        created = []
        real_tempfile = tempfile.TemporaryFile
        def tracked_tempfile(*args, **kwargs):
            stream = real_tempfile(*args, **kwargs)
            created.append(stream)
            return stream
        with patch('src.core.handlers.tempfile.TemporaryFile', side_effect=tracked_tempfile):
            self.assertEqual(self.request('/api/zip?path=/')[0], 200)
            with patch('src.core.handlers.build_archive', side_effect=HTTPResourceError(503, 'cancelled')):
                self.assertEqual(self.request('/api/zip?path=/')[0], 503)
            with patch('src.core.handlers.CustomHandler.copyfile', side_effect=ConnectionAbortedError('client left')):
                with self.assertRaises(http.client.IncompleteRead):
                    self.request('/api/zip?path=/')
        deadline = time.monotonic() + 2
        while not all(stream.closed for stream in created):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        self.assertTrue(all(stream.closed for stream in created))
        self.assertEqual((self.root / 'old.txt').read_bytes(), b'original')

    def test_invalid_configuration_is_rejected_before_binding(self):
        for options in ({'max_connections': 0}, {'body_timeout': float('nan')},
                        {'max_upload_bytes': -1}, {'rate_limit': 10001}):
            ok, _ = self.server.start_server('127.0.0.1', 0, str(self.root), **options)
            self.assertFalse(ok)
            self.assertIsNone(self.server.httpd)
