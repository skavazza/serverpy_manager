import http.client
import os
from pathlib import Path
import socket
import ssl
import shutil
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import urllib.request
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from src.core.server import ServerManager
from src.core.transfers import TransferMonitor, TransferCancelled, CancellableReader
from src.gui.i18n import InterfaceLanguage
from src.gui.transfers import TransfersPanel

OPENSSL = shutil.which('openssl')
if not OPENSSL and Path('C:/Program Files/Git/usr/bin/openssl.exe').is_file():
    OPENSSL = 'C:/Program Files/Git/usr/bin/openssl.exe'


class TestTransferMonitor(unittest.TestCase):
    def test_idle_reader_has_a_deadline_and_obeys_cancellation(self):
        sender, receiver = socket.socketpair()
        with sender, receiver:
            event = threading.Event()
            with CancellableReader(receiver.makefile('rb', buffering=0), receiver, event, idle_timeout=.02) as reader:
                with self.assertRaises(TimeoutError):
                    reader.readinto(bytearray(10))
                event.set()
                with self.assertRaises(ConnectionAbortedError):
                    reader.readinto(bytearray(10))
    def test_rates_cancellation_and_commit_are_consistent(self):
        now = [0]
        monitor = TransferMonitor(clock=lambda: now[0])
        cancel, commit = Mock(), Mock()
        token = monitor.begin('Upload', '/file?secret=hidden', 100, '127.0.0.1', cancel)
        now[0] = 1
        monitor.advance(token, 40)
        item = monitor.snapshot()[0]
        self.assertEqual((item['done'], item['rate'], item['remaining']), (40, 40, 1.5))
        self.assertNotIn('secret', repr(item))
        self.assertTrue(monitor.cancel(token))
        self.assertFalse(monitor.cancel(token))
        cancel.assert_called_once()
        with self.assertRaises(TransferCancelled):
            monitor.complete(token, commit)
        commit.assert_not_called()
        monitor.fail(token)
        self.assertEqual(monitor.snapshot()[0]['state'], 'Cancelled')

    def test_complete_protects_published_file_and_history_is_bounded(self):
        monitor = TransferMonitor(history_limit=2)
        for _ in range(3):
            token = monitor.begin('Upload', '/file', 2, 'client', Mock())
            monitor.advance(token, 2)
            commit = Mock()
            monitor.complete(token, commit)
            commit.assert_called_once()
            self.assertFalse(monitor.cancel(token))
        self.assertEqual(len(monitor.snapshot()), 2)
        self.assertTrue(all(item['state'] == 'Completed' for item in monitor.snapshot()))

    def test_download_tokens_are_hidden(self):
        monitor = TransferMonitor()
        monitor.begin('Download', '/_download/' + 'a' * 43, 1, 'client', Mock())
        self.assertNotIn('a' * 43, repr(monitor.snapshot()))


class TestTransferHTTP(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.other = self.root / 'mounted'
        self.other.mkdir()
        self.server = ServerManager()
        ok, message = self.server.start_server('127.0.0.1', 0, str(self.root), allow_mod=True, render_pages=True,
            shared_folders=[{'name': 'extra', 'path': str(self.other), 'writable': True}])
        self.assertTrue(ok, message)
        self.port = self.server.httpd.server_address[1]
        self.base = 'http://127.0.0.1:' + str(self.port)

    def tearDown(self):
        self.server.stop_server()
        self.wait_for(lambda: not self.server.transfers.active)
        self.temp.cleanup()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if predicate():
                return
            threading.Event().wait(.01)
        self.fail('Transfer did not reach the expected state')

    def begin_upload(self, path='/file.bin', length='1024', data=b'x' * 32, exclusive=True):
        connection = socket.create_connection(('127.0.0.1', self.port), timeout=3)
        self.addCleanup(connection.close)
        headers = f'PUT {path} HTTP/1.1\r\nHost: localhost\r\nContent-Length: {length}\r\n'
        if exclusive:
            headers += 'If-None-Match: *\r\n'
        connection.sendall((headers + '\r\n').encode() + data)
        return connection

    def read_response(self, connection):
        response = http.client.HTTPResponse(connection)
        response.begin()
        response.read()
        status = response.status
        response.close()
        return status

    def test_partial_upload_is_hidden_until_atomic_completion(self):
        connection = self.begin_upload()
        self.wait_for(lambda: self.server.transfers.snapshot() and self.server.transfers.snapshot()[0]['done'] == 32)
        self.assertFalse((self.root / 'file.bin').exists())
        with urllib.request.urlopen(self.base + '/') as response:
            self.assertNotIn(b'data-name=".serverpy"', response.read())
        connection.sendall(b'x' * 992)
        self.assertEqual(self.read_response(connection), 201)
        self.assertEqual((self.root / 'file.bin').read_bytes(), b'x' * 1024)
        self.assertEqual(self.server.transfers.snapshot()[0]['state'], 'Completed')
        self.assertEqual(list((self.root / '.serverpy' / 'uploads').iterdir()), [])

    def test_aborted_overwrite_preserves_original_and_retries(self):
        target = self.root / 'file.bin'
        target.write_bytes(b'original')
        connection = self.begin_upload(exclusive=False)
        self.wait_for(lambda: bool(self.server.transfers.active))
        self.assertEqual(target.read_bytes(), b'original')
        connection.shutdown(socket.SHUT_WR)
        self.assertEqual(self.read_response(connection), 400)
        self.wait_for(lambda: not self.server.transfers.active)
        self.assertEqual(target.read_bytes(), b'original')
        self.assertEqual(self.server.transfers.snapshot()[0]['state'], 'Interrupted')
        self.assertEqual(list((self.root / '.serverpy' / 'uploads').iterdir()), [])
        request = urllib.request.Request(self.base + '/file.bin', data=b'retried', method='PUT')
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 201)
        self.assertEqual(target.read_bytes(), b'retried')

    def test_desktop_cancellation_wakes_blocked_reader_and_discards_partial(self):
        connection = self.begin_upload('/_shares/extra/cancel.bin')
        self.wait_for(lambda: bool(self.server.transfers.active))
        item = self.server.transfers.snapshot()[0]
        self.assertEqual(item['path'], '/_shares/extra/cancel.bin')
        self.assertTrue(self.server.transfers.cancel(item['id']))
        self.wait_for(lambda: not self.server.transfers.active)
        self.wait_for(lambda: not list((self.other / '.serverpy' / 'uploads').iterdir()))
        self.assertFalse((self.other / 'cancel.bin').exists())
        self.assertEqual(self.server.transfers.snapshot()[0]['state'], 'Cancelled')

    def test_concurrent_exclusive_uploads_never_overwrite_each_other(self):
        first = self.begin_upload(length='64', data=b'a' * 32)
        second = self.begin_upload(length='64', data=b'b' * 32)
        self.wait_for(lambda: len(self.server.transfers.active) == 2)
        first.sendall(b'a' * 32)
        self.assertEqual(self.read_response(first), 201)
        second.sendall(b'b' * 32)
        self.assertEqual(self.read_response(second), 412)
        self.assertEqual(self.server.transfers.snapshot()[0]['state'], 'Failed')
        self.assertEqual((self.root / 'file.bin').read_bytes(), b'a' * 64)

    def test_invalid_length_and_zero_length_file(self):
        for length in ('-1', 'invalid'):
            connection = self.begin_upload(length=length, data=b'')
            self.assertEqual(self.read_response(connection), 400)
            self.assertFalse((self.root / 'file.bin').exists())
        connection = self.begin_upload(length='0', data=b'')
        self.assertEqual(self.read_response(connection), 201)
        self.assertEqual((self.root / 'file.bin').stat().st_size, 0)

    def test_file_download_counts_body_and_ignores_head_and_pages(self):
        (self.root / 'source.bin').write_bytes(b'x' * 12000)
        for path, method in (('/', 'GET'), ('/source.bin', 'HEAD')):
            with urllib.request.urlopen(urllib.request.Request(self.base + path, method=method)) as response:
                response.read()
        self.assertEqual(self.server.transfers.snapshot(), [])
        with urllib.request.urlopen(self.base + '/source.bin') as response:
            self.assertEqual(len(response.read()), 12000)
        self.wait_for(lambda: not self.server.transfers.active)
        item = self.server.transfers.snapshot()[0]
        self.assertEqual((item['direction'], item['done'], item['size'], item['state']), ('Download', 12000, 12000, 'Completed'))

    def test_cancel_download_to_client_that_is_not_reading(self):
        (self.root / 'large.bin').write_bytes(b'x' * (16 * 1024 * 1024))
        connection = socket.socket()
        self.addCleanup(connection.close)
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        connection.settimeout(3)
        connection.connect(('127.0.0.1', self.port))
        connection.sendall(b'GET /large.bin HTTP/1.1\r\nHost: localhost\r\n\r\n')
        self.wait_for(lambda: bool(self.server.transfers.active))
        item = self.server.transfers.snapshot()[0]
        self.server.transfers.cancel(item['id'])
        self.wait_for(lambda: not self.server.transfers.active)
        self.assertEqual(self.server.transfers.snapshot()[0]['state'], 'Cancelled')

    def test_server_stop_cancels_pending_upload(self):
        self.begin_upload()
        self.wait_for(lambda: bool(self.server.transfers.active))
        self.server.stop_server()
        self.wait_for(lambda: not self.server.transfers.active)
        self.assertEqual(self.server.transfers.snapshot()[0]['state'], 'Cancelled')
        self.assertFalse((self.root / 'file.bin').exists())

    @unittest.skipUnless(OPENSSL, 'OpenSSL is required to create an ephemeral TLS test certificate')
    def test_https_upload_and_download_with_verified_test_certificate(self):
        self.server.stop_server()
        with tempfile.TemporaryDirectory(prefix='serverpy_tls_') as scratch:
            key, cert, combined = (Path(scratch) / name for name in ('key.pem', 'cert.pem', 'combined.pem'))
            result = subprocess.run([OPENSSL, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                '-keyout', str(key), '-out', str(cert), '-days', '1', '-subj', '/CN=localhost',
                '-addext', 'subjectAltName=IP:127.0.0.1'], capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            combined.write_bytes(cert.read_bytes() + key.read_bytes())
            ok, message = self.server.start_server('127.0.0.1', 0, str(self.root),
                allow_mod=True, use_tls=True, cert_file=str(combined))
            self.assertTrue(ok, message)
            base = 'https://127.0.0.1:' + str(self.server.httpd.server_address[1])
            context = ssl.create_default_context(cafile=str(cert))
            body = b'verified TLS transfer' * 10000
            with urllib.request.urlopen(urllib.request.Request(base + '/tls.bin', data=body, method='PUT'), context=context, timeout=4) as response:
                self.assertEqual(response.status, 201)
            with urllib.request.urlopen(base + '/tls.bin', context=context, timeout=4) as response:
                self.assertEqual(response.read(), body)
            self.wait_for(lambda: not self.server.transfers.active)
            self.assertEqual([item['state'] for item in self.server.transfers.snapshot()], ['Completed', 'Completed'])


class TestTransfersGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_progress_translation_cancellation_and_session_changes(self):
        controller = SimpleNamespace(language=InterfaceLanguage('pt'), server_manager=SimpleNamespace(transfers=TransferMonitor()))
        cancel = Mock()
        token = controller.server_manager.transfers.begin('Upload', '/file', 100, 'client', cancel)
        controller.server_manager.transfers.advance(token, 25)
        panel = TransfersPanel(controller)
        self.addCleanup(panel.close)
        panel.table.selectRow(0)
        self.assertEqual(panel.table.item(0, 4).text(), '25%')
        self.assertTrue(panel.cancel_button.isEnabled())
        controller.language.code = 'en'
        panel.retranslate()
        self.assertEqual(panel.selected_id(), token)
        panel.cancel_button.click()
        cancel.assert_called_once()
        self.assertFalse(panel.cancel_button.isEnabled())
        controller.server_manager.transfers = TransferMonitor()
        panel.refresh()
        self.assertEqual(panel.table.rowCount(), 0)
        self.assertFalse(panel.cancel_button.isEnabled())
