import http.client
import io
import json
from email.message import Message
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from src.core.server import ServerManager
from src.core.handlers import resolve_client_ip
from src.core.traffic import TrafficMonitor, CountingStream


class TestTrafficMonitor(unittest.TestCase):
    def test_cloudflare_client_ip_is_trusted_only_from_loopback(self):
        headers = {'CF-Connecting-IP': '203.0.113.7'}
        self.assertEqual(resolve_client_ip('127.0.0.1', headers, True), '203.0.113.7')
        self.assertEqual(resolve_client_ip('::1', headers, True), '203.0.113.7')
        self.assertEqual(resolve_client_ip('::ffff:127.0.0.1', headers, True), '203.0.113.7')
        self.assertEqual(resolve_client_ip('192.0.2.5', headers, True), '192.0.2.5')
        self.assertEqual(resolve_client_ip('127.0.0.1', headers, False), '127.0.0.1')
        duplicate_headers = Message()
        duplicate_headers.add_header('CF-Connecting-IP', '203.0.113.7')
        duplicate_headers.add_header('CF-Connecting-IP', '198.51.100.2')
        self.assertEqual(resolve_client_ip('127.0.0.1', duplicate_headers, True), '127.0.0.1')
        self.assertEqual(
            resolve_client_ip('127.0.0.1', {'CF-Connecting-IP': 'bad, 203.0.113.7'}, True),
            '127.0.0.1',
        )

    def test_connection_client_ip_can_be_reassigned_before_request(self):
        monitor = TrafficMonitor()
        token = monitor.open_connection('127.0.0.1')
        monitor.set_client_ip(token, '203.0.113.7')
        monitor.start_request(token, 'GET', '/')
        self.assertEqual(monitor.snapshot()['clients'][0]['ip'], '203.0.113.7')
        monitor.close_connection(token)
        self.assertEqual(monitor.snapshot()['clients'][0]['connections'], 0)

    def test_rates_history_and_client_expiry(self):
        now = [0.0]
        monitor = TrafficMonitor(clock=lambda: now[0])
        token = monitor.open_connection('127.0.0.1')
        monitor.begin_cycle(token)
        monitor.add_bytes(token, 'received', 40)
        monitor.start_request(token, 'GET', '/_shares/docs/file?password=private')
        monitor.add_bytes(token, 'received', 60)
        monitor.add_bytes(token, 'sent', 200)
        monitor.set_status(token, 200)
        now[0] = 2
        active = monitor.snapshot()
        self.assertEqual(active['receive_rate'], 50)
        self.assertEqual(active['send_rate'], 100)
        self.assertEqual(active['active_requests'], 1)
        monitor.finish_request(token)
        monitor.close_connection(token)
        finished = monitor.snapshot()
        self.assertEqual(finished['connections'], 0)
        self.assertEqual(finished['clients'][0]['requests'], 1)
        self.assertEqual(finished['activity'][0]['received'], 100)
        self.assertEqual(finished['activity'][0]['path'], '/_shares/docs/file')
        self.assertNotIn('private', repr(finished))
        now[0] = 7
        self.assertEqual(monitor.snapshot()['send_rate'], 0)
        now[0] = 303
        expired = monitor.snapshot()
        self.assertEqual(expired['clients'], [])
        self.assertEqual(expired['sent'], 200)

    def test_history_and_inactive_client_memory_are_bounded(self):
        monitor = TrafficMonitor(recent_limit=3, client_limit=2)
        for index in range(6):
            token = monitor.open_connection(str(index))
            monitor.begin_cycle(token)
            monitor.start_request(token, 'GET', '/' + str(index))
            monitor.set_status(token, 404)
            monitor.close_connection(token)
        data = monitor.snapshot()
        self.assertEqual(len(data['activity']), 3)
        self.assertEqual(len(data['clients']), 2)
        self.assertEqual(data['requests'], 6)
        self.assertEqual(data['errors'], 6)

    def test_concurrent_requests_keep_exact_totals(self):
        monitor = TrafficMonitor()
        def request(index):
            token = monitor.open_connection(str(index % 3))
            monitor.begin_cycle(token)
            monitor.start_request(token, 'GET', '/file')
            monitor.add_bytes(token, 'received', 100)
            monitor.add_bytes(token, 'sent', 200)
            monitor.set_status(token, 200)
            monitor.close_connection(token)
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(request, range(100)))
        data = monitor.snapshot()
        self.assertEqual((data['received'], data['sent'], data['requests']), (10000, 20000, 100))
        self.assertEqual(data['connections'], 0)
        self.assertEqual(sum(client['requests'] for client in data['clients']), 100)

    def test_stream_counts_and_interruptions(self):
        monitor = TrafficMonitor()
        token = monitor.open_connection('127.0.0.1')
        monitor.begin_cycle(token)
        reader = CountingStream(io.BytesIO(b'header\r\nbody'), monitor, token, 'received')
        self.assertEqual(reader.readline(), b'header\r\n')
        monitor.start_request(token, 'PUT', '/file')
        self.assertEqual(reader.read(10), b'body')
        monitor.set_status(token, 201)
        monitor.close_connection(token)
        data = monitor.snapshot()
        self.assertEqual(data['received'], 12)
        self.assertTrue(data['activity'][0]['interrupted'])
        self.assertEqual(data['errors'], 1)

        class BrokenWriter:
            def write(self, data):
                raise BrokenPipeError('disconnected')
        token = monitor.open_connection('127.0.0.1')
        monitor.begin_cycle(token)
        monitor.start_request(token, 'GET', '/file')
        monitor.set_status(token, 200)
        writer = CountingStream(BrokenWriter(), monitor, token, 'sent')
        with self.assertRaises(BrokenPipeError):
            writer.write(b'not sent')
        monitor.close_connection(token)
        self.assertEqual(monitor.snapshot()['sent'], 0)
        self.assertTrue(monitor.snapshot()['activity'][0]['interrupted'])


class TestHTTPActivityIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'file.bin').write_bytes(b'x' * 8192)
        self.server = ServerManager()
        ok, message = self.server.start_server('127.0.0.1', 0, str(self.root), allow_mod=True, render_pages=True)
        self.assertTrue(ok, message)
        self.port = self.server.httpd.server_address[1]
        self.url = 'http://127.0.0.1:' + str(self.port)

    def tearDown(self):
        self.server.stop_server()
        self.temp.cleanup()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            data = self.server.traffic.snapshot()
            if predicate(data):
                return data
            threading.Event().wait(0.01)
        self.fail('HTTP activity did not reach the expected state')

    def test_download_upload_head_and_restart(self):
        headers = {'Authorization': 'Basic do-not-retain-this-header'}
        with urllib.request.urlopen(urllib.request.Request(self.url + '/file.bin?token=private-token', headers=headers), timeout=3) as response:
            self.assertEqual(len(response.read()), 8192)
        first = self.wait_for(lambda data: len(data['activity']) == 1 and not data['connections'])
        self.assertGreater(first['sent'], 8192)
        self.assertNotIn('private-token', repr(first))
        self.assertNotIn('do-not-retain', repr(first))
        with urllib.request.urlopen(urllib.request.Request(self.url + '/file.bin', method='HEAD'), timeout=3) as response:
            self.assertEqual(response.read(), b'')
        second = self.wait_for(lambda data: data['requests'] == 2 and not data['connections'])
        self.assertLess(second['sent'] - first['sent'], 8192)
        body = json.dumps({'path': '/saved.txt', 'content': 'do-not-record-body'}).encode()
        request = urllib.request.Request(self.url + '/api/save', data=body, method='POST', headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=3):
            pass
        third = self.wait_for(lambda data: data['requests'] == 3 and not data['connections'])
        self.assertGreaterEqual(third['received'] - second['received'], len(body))
        self.assertNotIn('do-not-record-body', repr(third))
        self.server.stop_server()
        self.assertEqual(self.server.traffic.snapshot()['requests'], 3)
        ok, message = self.server.start_server('127.0.0.1', 0, str(self.root))
        self.assertTrue(ok, message)
        self.assertEqual(self.server.traffic.snapshot()['requests'], 0)

    def test_cloudflare_tunnel_host_and_client_ip(self):
        config = self.server.httpd.app_config
        config.update({
            'verify_host': True,
            'cloudflare_tunnel': True,
            'cloudflare_hostname': 'files.example.com',
            'whitelist': ['203.0.113.7'],
        })
        request = urllib.request.Request(
            self.url + '/file.bin',
            headers={
                'Host': 'files.example.com',
                'CF-Connecting-IP': '203.0.113.7',
            },
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 200)
            response.read()
        activity = self.wait_for(lambda data: data['requests'] == 1 and not data['connections'])
        self.assertEqual(activity['clients'][0]['ip'], '203.0.113.7')
        self.assertEqual(activity['activity'][0]['ip'], '203.0.113.7')
        self.assertEqual(activity['clients'][0]['received'], activity['activity'][0]['received'])

    def test_cloudflare_host_validation_rejects_other_domains(self):
        self.server.httpd.app_config.update({
            'verify_host': True,
            'cloudflare_tunnel': True,
            'cloudflare_hostname': 'files.example.com',
        })
        request = urllib.request.Request(
            self.url + '/file.bin',
            headers={'Host': 'attacker.example.net', 'CF-Connecting-IP': '203.0.113.7'},
        )
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(error.exception.code, 400)

    def test_cloudflare_hostname_is_not_allowed_when_tunnel_mode_is_disabled(self):
        self.server.httpd.app_config.update({
            'verify_host': True,
            'cloudflare_tunnel': False,
            'cloudflare_hostname': 'files.example.com',
        })
        request = urllib.request.Request(
            self.url + '/file.bin',
            headers={'Host': 'files.example.com'},
        )
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(error.exception.code, 400)

    def test_upload_is_visible_while_request_is_in_progress(self):
        connection = socket.create_connection(('127.0.0.1', self.port), timeout=3)
        try:
            connection.sendall(b'PUT /slow.bin HTTP/1.1\r\nHost: localhost\r\nContent-Length: 1024\r\n\r\n' + b'x' * 32)
            active = self.wait_for(lambda data: data['active_requests'] == 1)
            self.assertEqual(active['connections'], 1)
            self.assertEqual(active['active_clients'], 1)
            self.assertTrue(active['activity'][0]['active'])
            self.assertEqual(active['activity'][0]['path'], '/slow.bin')
            connection.sendall(b'x' * (1024 - 32))
            response = http.client.HTTPResponse(connection)
            response.begin()
            self.assertEqual(response.status, 201)
            response.read()
            response.close()
        finally:
            connection.close()
        final = self.wait_for(lambda data: not data['connections'])
        self.assertEqual(final['active_requests'], 0)
        self.assertFalse(final['activity'][0]['active'])
        self.assertGreaterEqual(final['received'], 1024)
        self.assertEqual((self.root / 'slow.bin').stat().st_size, 1024)
