"""Bounded HTTPS admission endpoint; never starts or approves a VPN tunnel."""

import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
from pathlib import Path
import socket
from socketserver import ThreadingMixIn
import ssl
import threading
import time

from src.core.vpn_enrollment import RemoteInvite, _decode


class _HeaderReader:
    def __init__(self, stream):
        self.stream = stream
        self.remaining = 8192

    def readline(self, limit=-1):
        if self.remaining is None:
            return self.stream.readline(limit)
        if self.remaining <= 0:
            raise http.client.LineTooLong('admission headers')
        value = self.stream.readline(min(limit if limit >= 0 else 8193, self.remaining + 1))
        self.remaining -= len(value)
        if self.remaining < 0:
            raise http.client.LineTooLong('admission headers')
        return value

    def __getattr__(self, name):
        return getattr(self.stream, name)


class _AdmissionHTTP(ThreadingMixIn, HTTPServer):
    daemon_threads = False
    block_on_close = True
    request_queue_size = 4
    allow_reuse_address = False

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def finish_request(self, request, client_address):
        current = [request]
        def expire():
            try:
                current[0].shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        timer = threading.Timer(self.connection_deadline, expire)
        timer.daemon = True
        timer.start()
        try:
            request.settimeout(3)
            # Handshake runs inside the bounded worker, not the accept loop.
            with self.tls.wrap_socket(request, server_side=True, do_handshake_on_connect=False) as secure:
                current[0] = secure
                secure.do_handshake()
                super().finish_request(secure, client_address)
                # Deliver rejection responses before closing on unread bodies.
                # Drain is bounded; hostile senders cannot retain a worker.
                try:
                    secure.shutdown(socket.SHUT_WR)
                    secure.settimeout(0.1)
                    for _ in range(4):
                        if not secure.recv(4096):
                            break
                except OSError:
                    pass
        except (OSError, http.client.HTTPException):
            pass
        finally:
            timer.cancel()

    def handle_error(self, request, client_address):
        # Request bodies and exceptions may contain invitation credentials.
        pass

    def allowed(self, address):
        now = time.monotonic()
        with self.rate_lock:
            self.attempts = {key: value for key, value in self.attempts.items() if now - value[0] < 60}
            if now - self.window_start >= 60:
                self.window_start, self.total = now, 0
            start, count = self.attempts.get(address, (now, 0))
            if count >= 10 or self.total >= 60 or (address not in self.attempts and len(self.attempts) >= 256):
                return False
            self.attempts[address] = (start, count + 1)
            self.total += 1
            return True


class _Handler(BaseHTTPRequestHandler):
    server_version = 'ServerPyAdmission'
    sys_version = ''
    protocol_version = 'HTTP/1.0'

    def setup(self):
        super().setup()
        self.rfile = _HeaderReader(self.rfile)

    def parse_request(self):
        result = super().parse_request()
        if result:
            self.rfile.remaining = None
            if not self.server.allowed(self.client_address[0]):
                self.reply(429)
                return False
        return result

    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.reply(code)

    def reply(self, code, data=None):
        import json
        payload = json.dumps(data if data is not None else {'error': 'request rejected'}, separators=(',', ':')).encode()
        self.close_connection = True
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if self.path != '/vpn/v1/requests':
            self.reply(404)
            return
        lengths = self.headers.get_all('Content-Length', [])
        if ('Transfer-Encoding' in self.headers or len(lengths) != 1
                or not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 5):
            self.reply(400)
            return
        length = int(lengths[0])
        if not 0 < length <= 2048:
            self.reply(413)
            return
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            self.reply(415)
            return
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                self.reply(400)
                return
            data = _decode(body.decode('utf-8'))
            if set(data) != {'token', 'public_key', 'name'}:
                raise ValueError
        except (ValueError, UnicodeError):
            self.reply(400)
            return
        try:
            request_id = self.server.registry.request_admission(data['token'], data['public_key'], data['name'])
        except ValueError:
            self.reply(403)
            return
        except Exception:
            self.reply(503)
            return
        self.reply(202, {'request_id': request_id, 'state': 'pending',
                         'server_public_key': self.server.registry.server_public_key})


class AdmissionServer:
    """Explicitly started IPv4 listener using an existing TLS certificate/key.

    Defaults to loopback. Caller owns certificate protection and bind selection.
    Rate limits are in-memory and reset on restart. No firewall changes occur.
    """

    def __init__(self, registry, certfile, keyfile, *, host='127.0.0.1', port=0):
        address = ipaddress.ip_address(host)
        if address.version != 4 or address.is_multicast or type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('Invalid enrollment listener address.')
        pem = Path(certfile).read_bytes()
        if len(pem) > 8192 or b'PRIVATE KEY' in pem:
            raise ValueError('Provide a public certificate separately from the private key.')
        self.certificate_pem = pem.decode('ascii')
        self.fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(self.certificate_pem)).hexdigest()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile, keyfile, password=lambda: '')
        context.set_alpn_protocols(['http/1.1'])
        self.server = _AdmissionHTTP((str(address), port), _Handler)
        self.server.registry = registry
        self.server.tls = context
        self.server.slots = threading.BoundedSemaphore(4)
        self.server.connection_deadline = 5
        self.server.rate_lock = threading.Lock()
        self.server.attempts = {}
        self.server.window_start, self.server.total = time.monotonic(), 0
        self.thread = None
        self.closed = False

    @property
    def port(self):
        return self.server.server_port

    def start(self):
        if self.thread is not None or self.closed:
            raise ValueError('Enrollment listener cannot be started twice.')
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
        try:
            self.thread.start()
        except BaseException:
            self.server.server_close()
            self.closed = True
            raise
        return self

    def stop(self):
        if not self.closed:
            if self.thread is not None:
                self.server.shutdown()
                self.thread.join(5)
            self.server.server_close()
            self.closed = True

    def create_invite(self, host, ttl=900):
        if self.closed or self.thread is None:
            raise ValueError('Enrollment listener is not running.')
        # Validate destination/certificate before issuing an invitation token.
        from src.core.vpn import validate_endpoint
        validate_endpoint(host, self.port)
        local = self.server.registry.create_invite(ttl)
        return RemoteInvite(host, self.port, self.server.registry.server_public_key,
                            self.certificate_pem, self.fingerprint, local.token, local.expires_at).validate()
