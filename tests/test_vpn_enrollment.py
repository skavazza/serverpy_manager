from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
from pathlib import Path
import ssl
import tempfile
from threading import Thread
import unittest

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID

from src.core.vpn import generate_identity
from src.core.vpn_enrollment import RemoteInvite, request_remote_admission
from src.core.vpn_registry import VPNRegistry


class TestVPNEnrollment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                       .public_key(key.public_key()).serial_number(x509.random_serial_number())
                       .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
                       .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                       .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
                       .sign(key, hashes.SHA256()))
        cls.pem = certificate.public_bytes(serialization.Encoding.PEM).decode('ascii')
        cls.fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
        cls.key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / 'cert.pem').write_text(self.pem, encoding='ascii')
        (root / 'key.pem').write_bytes(self.key_pem)
        self.server_key = generate_identity().public_key
        self.registry = VPNRegistry(root / 'registry.sqlite', '10.77.0.0/24', self.server_key)
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append(data)
                try:
                    request_id = owner.registry.request_admission(data['token'], data['public_key'], data['name'])
                    response = json.dumps({'request_id': request_id, 'state': 'pending', 'server_public_key': owner.server_key}).encode()
                    self.send_response(202)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(response)))
                    self.end_headers()
                    self.wfile.write(response)
                except ValueError:
                    self.send_error(403)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(root / 'cert.pem', root / 'key.pem')
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def invite(self, **changes):
        local = self.registry.create_invite()
        data = dict(host='127.0.0.1', port=self.server.server_port,
                    server_public_key=self.server_key, certificate_pem=self.pem,
                    certificate_sha256=self.fingerprint, token=local.token,
                    expires_at=local.expires_at)
        data.update(changes)
        return RemoteInvite(**data)

    def test_real_https_request_remains_pending_until_local_approval(self):
        invite = RemoteInvite.parse(self.invite().export())
        key = generate_identity().public_key
        request_id = request_remote_admission(invite, key, 'Notebook')
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.registry.authorized_peers(), ())
        self.assertEqual(self.registry.approve(request_id).public_key, key)
        with self.assertRaises(ValueError):
            request_remote_admission(invite, generate_identity().public_key, 'Replay')

    def test_wrong_fingerprint_sends_no_http_credentials(self):
        invite = self.invite(certificate_sha256='0' * 64)
        with self.assertRaises(ValueError):
            request_remote_admission(invite, generate_identity().public_key, 'Notebook')
        self.assertEqual(self.requests, [])

    def test_peer_certificate_pin_checked_before_http_post(self):
        from unittest.mock import patch
        invite = self.invite()
        original = ssl.SSLSocket.getpeercert
        def wrong_peer(socket, binary_form=False):
            return b'other-peer-certificate' if binary_form else original(socket, binary_form)
        with patch.object(ssl.SSLSocket, 'getpeercert', wrong_peer):
            with self.assertRaises(ValueError):
                request_remote_admission(invite, generate_identity().public_key, 'Notebook')
        self.assertEqual(self.requests, [])

    def test_invalid_hostname_certificate_is_rejected_before_request(self):
        # Connect to the same listener using an alternate loopback IP absent
        # from the certificate. Bind-independent validation mocked at connect.
        from unittest.mock import patch
        real_connect = __import__('socket').create_connection
        def connect(address, *args, **kwargs):
            return real_connect(('127.0.0.1', address[1]), *args, **kwargs)
        with patch('socket.create_connection', side_effect=connect):
            with self.assertRaises(OSError):
                request_remote_admission(self.invite(host='wrong.example'), generate_identity().public_key, 'Notebook')
        self.assertEqual(self.requests, [])

    def test_strict_import_rejects_expired_oversized_duplicate_and_unknown_fields(self):
        invite = self.invite()
        payload = invite.export()
        values = json.loads(payload)
        values['unexpected'] = 'value'
        for invalid in (payload[:-1] + ',"version":1}', json.dumps(values), ' ' * 16385,
                        payload.replace('"version":1', '"version":true')):
            with self.subTest(invalid=invalid[:30]), self.assertRaises(ValueError):
                RemoteInvite.parse(invalid)
        with self.assertRaises(ValueError):
            RemoteInvite.parse(payload, now=invite.expires_at)
        self.assertNotIn(invite.token, repr(invite))

    def test_tampered_server_key_response_does_not_authorize_connection(self):
        invite = self.invite(server_public_key=generate_identity().public_key)
        with self.assertRaises(ValueError):
            request_remote_admission(invite, generate_identity().public_key, 'Notebook')
        self.assertEqual(self.registry.authorized_peers(), ())


if __name__ == '__main__':
    unittest.main()
