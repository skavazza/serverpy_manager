"""Revocable, session-only grants to download individual shared files."""

from collections import OrderedDict
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time

from .explorer import ExplorerError


DOWNLOAD_PREFIX = '/_download/'
TOKEN_PATTERN = re.compile(r'[A-Za-z0-9_-]{43}')
_LOG_TOKEN = re.compile(r'/_download/[A-Za-z0-9_-]+')


def redact_download_tokens(text):
    return _LOG_TOKEN.sub(DOWNLOAD_PREFIX + '[link]', text)


class LinkError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class TemporaryLinks:
    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.lock = threading.RLock()
        self.records = {}

    @staticmethod
    def fingerprint(info):
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns

    @staticmethod
    def password_hash(password, salt):
        return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 600000)

    def create(self, explorer, filename, lifetime=3600, password=None, source='Main folder'):
        if isinstance(lifetime, bool) or not isinstance(lifetime, int) or not 60 <= lifetime <= 7 * 86400:
            raise LinkError(400, 'Choose a lifetime from 1 minute to 7 days.')
        if password is not None and (not isinstance(password, str) or not 1 <= len(password) <= 256):
            raise LinkError(400, 'Enter a link password with 1 to 256 characters.')
        try:
            relative = os.path.relpath(os.path.abspath(filename), explorer.root)
            path = explorer.resolve(relative)
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                raise OSError('Not a regular file')
        except (OSError, ValueError, TypeError, ExplorerError):
            raise LinkError(400, 'Select a file inside the chosen shared folder.') from None
        salt = secrets.token_bytes(16) if password is not None else None
        digest = self.password_hash(password, salt) if password is not None else None
        with self.lock:
            now = self.clock()
            self.records = {token: record for token, record in self.records.items()
                            if record['expires'] > now and not record['revoked'] and not record['invalid']}
            if len(self.records) >= 100:
                raise LinkError(400, 'Revoke an existing link before creating more than 100 links.')
            token = secrets.token_urlsafe(32)
            while token in self.records:
                token = secrets.token_urlsafe(32)
            self.records[token] = {
                'explorer': explorer, 'relative': relative, 'name': Path(path).name,
                'source': source, 'fingerprint': self.fingerprint(info),
                'expires': now + lifetime, 'salt': salt, 'digest': digest,
                'revoked': False, 'invalid': False, 'attempts': OrderedDict(),
            }
            return token

    def _lookup(self, token):
        if not isinstance(token, str) or TOKEN_PATTERN.fullmatch(token) is None or token not in self.records:
            raise LinkError(404, 'Link expired or unavailable.')
        record = self.records[token]
        if record['expires'] <= self.clock() or record['revoked'] or record['invalid']:
            raise LinkError(410, 'Link expired or unavailable.')
        return record

    def info(self, token):
        with self.lock:
            record = self._lookup(token)
            return {'name': record['name'], 'protected': record['digest'] is not None}

    def open_download(self, token, password=None, client_ip=''):
        with self.lock:
            record = self._lookup(token)
            if record['digest'] is not None:
                if password is None:
                    raise LinkError(403, 'A link password is required.')
                if not isinstance(password, str) or len(password) > 256:
                    raise LinkError(403, 'Incorrect link password.')
                now = self.clock()
                attempts = record['attempts']
                for ip in list(attempts):
                    if now - attempts[ip][0] >= 60:
                        del attempts[ip]
                start, count = attempts.get(client_ip, (now, 0))
                if count >= 10:
                    raise LinkError(429, 'Too many password attempts. Try again in a minute.')
                attempts[client_ip] = start, count + 1
                attempts.move_to_end(client_ip)
                while len(attempts) > 256:
                    attempts.popitem(last=False)
                salt, digest = record['salt'], record['digest']
            else:
                salt = digest = None
        if digest is not None:
            valid = hmac.compare_digest(digest, self.password_hash(password, salt))
            with self.lock:
                self._lookup(token)
            if not valid:
                raise LinkError(403, 'Incorrect link password.')
        with self.lock:
            record = self._lookup(token)
            stream = None
            try:
                path = record['explorer'].resolve(record['relative'])
                descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0))
                try:
                    stream = os.fdopen(descriptor, 'rb')
                except Exception:
                    os.close(descriptor)
                    raise
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or self.fingerprint(info) != record['fingerprint']:
                    raise OSError('Selected file changed')
            except (OSError, ValueError, ExplorerError):
                if stream is not None:
                    stream.close()
                record['invalid'] = True
                raise LinkError(410, 'The linked file changed or is unavailable.') from None
            return stream, record['name'], info.st_size

    def revoke(self, token):
        with self.lock:
            if token in self.records:
                self.records[token]['revoked'] = True

    def clear(self):
        with self.lock:
            self.records.clear()

    def snapshot(self):
        with self.lock:
            now = self.clock()
            return [{
                'token': token, 'name': record['name'], 'source': record['source'],
                'remaining': max(0, record['expires'] - now) if not record['revoked'] and not record['invalid'] else 0,
                'protected': record['digest'] is not None,
                'status': 'Revoked' if record['revoked'] else 'Unavailable' if record['invalid'] else
                          'Expired' if record['expires'] <= now else 'Valid',
            } for token, record in reversed(list(self.records.items()))]
