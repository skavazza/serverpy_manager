"""Validate user-configured HTTP response headers before serving requests."""
import re


def validate_response_headers(headers):
    rows = headers.items() if isinstance(headers, dict) else headers
    result = {}
    seen = set()
    reserved = {'content-length', 'transfer-encoding', 'connection', 'keep-alive',
                'trailer', 'upgrade', 'content-type', 'content-encoding', 'content-range',
                'content-disposition', 'server', 'date', 'location', 'www-authenticate',
                'proxy-authenticate', 'set-cookie'}
    for name, value in rows:
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError('Enter a valid HTTP header name and value.')
        name, value = name.strip(), value.strip(' ')
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
            raise ValueError('Enter a valid HTTP header name and value.')
        lowered = name.lower()
        if lowered in reserved or lowered.startswith('access-control-'):
            raise ValueError('This header is managed by the server or CORS settings.')
        if lowered in seen:
            raise ValueError('Each header name must appear only once.')
        if len(value) > 8192 or any(ord(char) < 32 or ord(char) == 127 or ord(char) > 255 for char in value):
            raise ValueError('Header values cannot contain control characters or characters outside Latin-1.')
        seen.add(lowered)
        result[name] = value
        if len(result) > 50:
            raise ValueError('Configure at most 50 custom headers.')
    return result
