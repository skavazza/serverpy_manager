import http.client
import json
from pathlib import Path
import socket
import ssl
import tempfile
import time
import unittest
from unittest.mock import patch

from src.core.vpn import generate_identity
from src.core.vpn_admission_server import AdmissionServer
from src.core.vpn_enrollment import RemoteInvite, request_remote_admission
from src.core.vpn_registry import VPNRegistry
from tests import test_vpn_enrollment as fixtures


class TestAdmissionServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.TestVPNEnrollment.setUpClass()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.cert, self.key = root / 'cert.pem', root / 'key.pem'
        self.cert.write_text(fixtures.TestVPNEnrollment.pem, encoding='ascii')
        self.key.write_bytes(fixtures.TestVPNEnrollment.key_pem)
        self.registry = VPNRegistry(root / 'registry.sqlite', '10.77.0.0/29', generate_identity().public_key)
        self.listener = AdmissionServer(self.registry, self.cert, self.key).start()
        self.addCleanup(self.listener.stop)

    def connect(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=self.listener.certificate_pem)
        return http.client.HTTPSConnection('127.0.0.1', self.listener.port, context=context, timeout=2)

    def post(self, body=b'{}', path='/vpn/v1/requests', headers=None):
        connection = self.connect()
        try:
            connection.request('POST', path, body, headers or {'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_real_client_server_invitation_pending_approval_and_replay(self):
        invite = RemoteInvite.parse(self.listener.create_invite('127.0.0.1').export())
        device_key = generate_identity().public_key
        request_id = request_remote_admission(invite, device_key, 'Other instance')
        self.assertEqual(self.registry.authorized_peers(), ())
        self.assertEqual(self.registry.approve(request_id).public_key, device_key)
        with self.assertRaises(ValueError):
            request_remote_admission(invite, generate_identity().public_key, 'Replay')
        self.assertEqual(len(self.registry.devices()), 1)

    def test_body_limits_schema_media_type_and_route_reject_without_db_write(self):
        for body, path, headers, expected in (
            (b'x' * 2049, '/vpn/v1/requests', None, 413),
            (b'{}', '/unknown', None, 404),
            (b'{}', '/vpn/v1/requests', {'Content-Type': 'text/plain'}, 415),
            (b'{"token":1,"token":2}', '/vpn/v1/requests', None, 400),
            (b'{}', '/vpn/v1/requests', None, 400),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(self.post(body, path, headers)[0], expected)
        self.assertEqual(self.registry.devices(), [])

    def test_attempts_are_limited_without_echoing_credentials(self):
        secret = 'invalid-private-token'
        body = json.dumps({'token': secret, 'public_key': generate_identity().public_key, 'name': 'Device'}).encode()
        for _ in range(10):
            status, response = self.post(body)
            self.assertEqual(status, 403)
            self.assertNotIn(secret.encode(), response)
        self.assertEqual(self.post(body)[0], 429)
        self.assertEqual(self.registry.devices(), [])

    def test_duplicate_content_length_and_transfer_encoding_are_rejected(self):
        for extra in ('Content-Length: 2\r\n', 'Transfer-Encoding: chunked\r\n'):
            connection = self.connect()
            connection.connect()
            connection.sock.sendall(('POST /vpn/v1/requests HTTP/1.0\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: 2\r\n' + extra + '\r\n{}').encode())
            response = http.client.HTTPResponse(connection.sock)
            response.begin()
            self.assertEqual(response.status, 400)
            response.read()
            connection.close()

    def test_tls_stall_does_not_block_accept_loop_and_slots_recover(self):
        self.listener.server.connection_deadline = 0.5
        raw = socket.create_connection(('127.0.0.1', self.listener.port), timeout=2)
        self.addCleanup(raw.close)
        # A non-TLS socket must not prevent a second valid client handshake.
        self.assertEqual(self.post()[0], 400)
        time.sleep(0.6)
        self.assertEqual(raw.recv(1), b'')
        self.assertEqual(self.post()[0], 400)

    def test_oversized_headers_are_closed_without_registry_write(self):
        connection = self.connect()
        connection.connect()
        connection.sock.sendall(b'POST /vpn/v1/requests HTTP/1.0\r\nX-Large: ' + b'x' * 9000 + b'\r\n\r\n')
        try:
            response = http.client.HTTPResponse(connection.sock)
            response.begin()
            self.assertEqual(response.status, 431)
            response.read()
        except http.client.RemoteDisconnected:
            pass
        finally:
            connection.close()
        self.assertEqual(self.registry.devices(), [])

    def test_internal_failure_is_generic_and_does_not_print_exception(self):
        invite = self.listener.create_invite('127.0.0.1')
        body = json.dumps({'token': invite.token, 'public_key': generate_identity().public_key, 'name': 'Device'}).encode()
        with patch.object(self.registry, 'request_admission', side_effect=OSError('secret-internal-details')):
            status, response = self.post(body)
        self.assertEqual(status, 503)
        self.assertNotIn(b'secret-internal-details', response)

    def test_stop_closes_port_and_prevents_new_invitations(self):
        port = self.listener.port
        self.listener.stop()
        self.listener.stop()
        with self.assertRaises(OSError):
            socket.create_connection(('127.0.0.1', port), timeout=1)
        with self.assertRaises(ValueError):
            self.listener.create_invite('127.0.0.1')


if __name__ == '__main__':
    unittest.main()
