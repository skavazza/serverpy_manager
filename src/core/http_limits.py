"""Resource budgets shared by the HTTP server and file APIs."""

import json
import math
import time

DEFAULT_LIMITS = {
    'max_post_bytes': 1024 * 1024,
    'max_upload_bytes': 4 * 1024 ** 3,
    'max_connections': 16,
    'request_timeout': 30,
    'body_timeout': 15,
    'upload_idle_timeout': 60,
    'upload_timeout': 3600,
    'rate_limit_max_ips': 4096,
    'rate_limit_ttl': 60,
    'zip_max_bytes': 1024 ** 3,
    'zip_max_entries': 10000,
    'zip_timeout': 120,
}


def validate_limits(config):
    for name, default in DEFAULT_LIMITS.items():
        value = config.setdefault(name, default)
        if isinstance(default, int) and ('timeout' not in name and name != 'rate_limit_ttl'):
            valid = type(value) is int and value > 0
        else:
            valid = type(value) in (int, float) and math.isfinite(value) and value > 0
        if not valid:
            raise ValueError('Invalid HTTP resource limit: ' + name)
    rate = config.get('rate_limit')
    if rate is not None and (type(rate) is not int or not 1 <= rate <= 10000):
        raise ValueError('Request rate limit must be between 1 and 10000.')
    if config['rate_limit_ttl'] < 1:
        raise ValueError('Rate limit history must be retained for at least one second.')


class HTTPResourceError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class RequestBodyLimits:
    def body_length(self, limit):
        lengths = self.headers.get_all('Content-Length', [])
        if self.headers.get('Transfer-Encoding') or len(lengths) > 1:
            raise HTTPResourceError(400, 'Invalid request framing')
        if not lengths:
            raise HTTPResourceError(411, 'Content-Length required')
        raw = lengths[0]
        if not raw.isascii() or not raw.isdigit() or len(raw) > 20:
            raise HTTPResourceError(400, 'Invalid Content-Length')
        length = int(raw)
        if length > limit:
            raise HTTPResourceError(413, 'Request body exceeds the configured limit')
        return length

    def read_json_body(self, limit=None):
        length = self.body_length(limit or self.config['max_post_bytes'])
        timeout = self.config['body_timeout']
        deadline = time.monotonic() + timeout
        previous = self.connection.gettimeout()
        data = bytearray()
        try:
            while len(data) < length:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                self.connection.settimeout(remaining)
                chunk = self.rfile.read1(min(length - len(data), 64 * 1024))
                if not chunk:
                    raise HTTPResourceError(400, 'Incomplete request body')
                data.extend(chunk)
        except TimeoutError:
            raise HTTPResourceError(408, 'Request body timed out') from None
        finally:
            self.connection.settimeout(previous)
        try:
            payload = json.loads(data.decode('utf-8'))
        except (ValueError, UnicodeError):
            raise HTTPResourceError(400, 'Invalid JSON body') from None
        if not isinstance(payload, dict):
            raise HTTPResourceError(400, 'JSON body must be an object')
        return payload
