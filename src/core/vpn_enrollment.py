"""Portable invitation format and authenticated HTTPS enrollment client.

No listener is opened here. Invitations are secrets and must arrive through a
trusted channel: the embedded certificate establishes the server's trust root.
"""

from dataclasses import dataclass, field
import hashlib
import hmac
import http.client
import json
import re
import ssl
import time

from src.core.vpn import validate_endpoint, validate_public_key
from src.core.vpn_registry import _device_name, _token_hash


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Invalid VPN message.')
        result[key] = value
    return result


def _decode(payload):
    try:
        if not isinstance(payload, str) or len(payload.encode('utf-8')) > 16384:
            raise ValueError
        value = json.loads(payload, object_pairs_hook=_unique_object)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('Invalid VPN message.') from None


@dataclass(frozen=True)
class RemoteInvite:
    host: str
    port: int
    server_public_key: str
    certificate_pem: str = field(repr=False)
    certificate_sha256: str
    token: str = field(repr=False)
    expires_at: int

    def validate(self, now=None):
        validate_endpoint(self.host, self.port)
        validate_public_key(self.server_public_key)
        _token_hash(self.token)
        now = time.time() if now is None else now
        if type(self.expires_at) is not int or not now < self.expires_at <= now + 86400:
            raise ValueError('VPN invitation has expired or has an invalid lifetime.')
        if not isinstance(self.certificate_pem, str) or len(self.certificate_pem) > 8192:
            raise ValueError('Invalid VPN server certificate.')
        if not isinstance(self.certificate_sha256, str) or not re.fullmatch('[a-f0-9]{64}', self.certificate_sha256):
            raise ValueError('Invalid VPN server certificate fingerprint.')
        try:
            der = ssl.PEM_cert_to_DER_cert(self.certificate_pem)
            if not hmac.compare_digest(hashlib.sha256(der).hexdigest(), self.certificate_sha256):
                raise ValueError
            # Parsing verifies it is a usable trust anchor, not merely base64.
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.load_verify_locations(cadata=self.certificate_pem)
        except (ValueError, ssl.SSLError):
            raise ValueError('Invalid VPN server certificate.') from None
        return self

    def export(self, now=None):
        self.validate(now)
        return json.dumps({'format': 'serverpy-vpn-invite', 'version': 1,
                          **self.__dict__}, separators=(',', ':'))

    @classmethod
    def parse(cls, payload, now=None):
        value = _decode(payload)
        expected = {'format', 'version', 'host', 'port', 'server_public_key',
                    'certificate_pem', 'certificate_sha256', 'token', 'expires_at'}
        if (set(value) != expected or value['format'] != 'serverpy-vpn-invite'
                or type(value['version']) is not int or value['version'] != 1):
            raise ValueError('Unsupported VPN invitation format.')
        del value['format'], value['version']
        return cls(**value).validate(now)


def request_remote_admission(invite, public_key, name, *, timeout=5):
    """Authenticate TLS chain, hostname AND exact certificate before sending token.

    Returns only a pending request ID, never a claim of approval or connectivity.
    WireGuard-key possession must subsequently be established by its handshake.
    """
    invite.validate()
    validate_public_key(public_key)
    _device_name(name)
    if public_key == invite.server_public_key:
        raise ValueError('The server cannot register itself as a participant.')
    if type(timeout) not in (int, float) or not 0 < timeout <= 30:
        raise ValueError('Invalid VPN enrollment timeout.')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cadata=invite.certificate_pem)
    context.set_alpn_protocols(['http/1.1'])
    connection = http.client.HTTPSConnection(invite.host, invite.port, context=context, timeout=timeout)
    try:
        connection.connect()
        fingerprint = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
        if not hmac.compare_digest(fingerprint, invite.certificate_sha256):
            raise ValueError('VPN server identity does not match the invitation.')
        # Explicit connection above authenticates the endpoint before credentials
        # leave memory. No redirects, proxies or fallback to HTTP are supported.
        body = json.dumps({'token': invite.token, 'public_key': public_key, 'name': name})
        connection.request('POST', '/vpn/v1/requests', body.encode('utf-8'),
                           {'Content-Type': 'application/json', 'Connection': 'close'})
        response = connection.getresponse()
        if response.status != 202 or response.getheader('Content-Type', '').split(';')[0] != 'application/json':
            raise ValueError('VPN enrollment was not accepted.')
        payload = response.read(4097)
        if len(payload) > 4096:
            raise ValueError('Invalid VPN enrollment response.')
        data = _decode(payload.decode('utf-8'))
        if (set(data) != {'request_id', 'state', 'server_public_key'}
                or data['state'] != 'pending'
                or data['server_public_key'] != invite.server_public_key
                or not isinstance(data['request_id'], str)
                or not re.fullmatch('[a-f0-9]{32}', data['request_id'])):
            raise ValueError('Invalid VPN enrollment response.')
        return data['request_id']
    except (OSError, http.client.HTTPException, UnicodeError):
        raise OSError('Could not complete authenticated VPN enrollment.') from None
    finally:
        connection.close()
