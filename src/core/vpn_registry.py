"""Local VPN admission registry. Transport authentication is not implemented here.

Only trusted local administration may call approval/revocation methods. No HTTP
routes are exposed; a future TLS layer must authenticate server and requests.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
import time

from src.core.vpn import PeerPlan, plan_peer, validate_network, validate_public_key


@dataclass(frozen=True)
class AdmissionInvite:
    token: str = field(repr=False)
    expires_at: int


def _device_name(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 80
            or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('Invalid VPN device name.')
    return value


def _token_hash(token):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise ValueError('VPN invitation is invalid or unavailable.')
    return hashlib.sha256(token.encode('ascii')).hexdigest()


class VPNRegistry:
    """SQLite transactions consume invitations and allocate addresses atomically.

    Private keys and plaintext invitation tokens are never persisted. Revoked
    device keys remain blocked and their addresses remain reserved.
    """

    def __init__(self, path, cidr, server_public_key, *, clock=time.time):
        self.path = Path(path)
        self.cidr = str(validate_network(cidr))
        self.server_public_key = validate_public_key(server_public_key)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS network (id INTEGER PRIMARY KEY CHECK(id=1), cidr TEXT NOT NULL, server_key TEXT NOT NULL)')
            connection.execute('CREATE TABLE IF NOT EXISTS invitations (verifier TEXT PRIMARY KEY, expires INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN (\'open\',\'used\',\'revoked\')))')
            connection.execute('CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, public_key TEXT UNIQUE NOT NULL, name TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN (\'pending\',\'approved\',\'rejected\',\'revoked\')), address TEXT UNIQUE, created INTEGER NOT NULL)')
            connection.execute('INSERT OR IGNORE INTO network VALUES (1, ?, ?)', (self.cidr, self.server_public_key))
            row = connection.execute('SELECT cidr, server_key FROM network WHERE id=1').fetchone()
            if tuple(row) != (self.cidr, self.server_public_key):
                raise ValueError('VPN registry belongs to another network or server identity.')

    @contextmanager
    def _transaction(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_invite(self, ttl=900):
        if type(ttl) is not int or not 60 <= ttl <= 86400:
            raise ValueError('Invitation lifetime must be 60 to 86400 seconds.')
        now = int(self.clock())
        token = secrets.token_urlsafe(32)
        with self._transaction() as connection:
            # Old verifiers are no longer needed: replay then fails as unknown.
            connection.execute('DELETE FROM invitations WHERE expires <= ? OR state != \'open\'', (now,))
            if connection.execute('SELECT COUNT(*) FROM invitations').fetchone()[0] >= 100:
                raise ValueError('Too many active VPN invitations.')
            connection.execute('INSERT INTO invitations VALUES (?, ?, \'open\')', (_token_hash(token), now + ttl))
        return AdmissionInvite(token, now + ttl)

    def revoke_invite(self, token):
        with self._transaction() as connection:
            result = connection.execute('UPDATE invitations SET state=\'revoked\' WHERE verifier=? AND state=\'open\'', (_token_hash(token),))
            if result.rowcount != 1:
                raise ValueError('VPN invitation is invalid or unavailable.')

    def request_admission(self, token, public_key, name):
        verifier = _token_hash(token)
        validate_public_key(public_key)
        _device_name(name)
        if public_key == self.server_public_key:
            raise ValueError('The server cannot register itself as a participant.')
        now = int(self.clock())
        device_id = secrets.token_hex(16)
        with self._transaction() as connection:
            row = connection.execute('SELECT expires, state FROM invitations WHERE verifier=?', (verifier,)).fetchone()
            if row is None or row['state'] != 'open' or row['expires'] <= now:
                raise ValueError('VPN invitation is invalid or unavailable.')
            if connection.execute('SELECT 1 FROM devices WHERE public_key=?', (public_key,)).fetchone():
                raise ValueError('This VPN device is already registered or blocked.')
            if connection.execute('SELECT COUNT(*) FROM devices').fetchone()[0] >= 4096:
                raise ValueError('VPN registry device capacity reached.')
            connection.execute('INSERT INTO devices VALUES (?, ?, ?, \'pending\', NULL, ?)', (device_id, public_key, name, now))
            connection.execute('UPDATE invitations SET state=\'used\' WHERE verifier=?', (verifier,))
        return device_id

    def approve(self, device_id):
        with self._transaction() as connection:
            row = connection.execute('SELECT * FROM devices WHERE id=?', (device_id,)).fetchone()
            if row is None or row['state'] != 'pending':
                raise ValueError('VPN device is not awaiting approval.')
            reserved = [PeerPlan(item['public_key'], item['address']) for item in connection.execute('SELECT public_key, address FROM devices WHERE address IS NOT NULL')]
            peer = plan_peer(self.cidr, row['public_key'], reserved)
            connection.execute('UPDATE devices SET state=\'approved\', address=? WHERE id=?', (peer.address, device_id))
        return peer

    def reject(self, device_id):
        self._transition(device_id, 'pending', 'rejected')

    def revoke(self, device_id):
        """Revoke registry authorization only; live peer removal needs service integration."""
        self._transition(device_id, 'approved', 'revoked')

    def _transition(self, device_id, old, new):
        with self._transaction() as connection:
            result = connection.execute('UPDATE devices SET state=? WHERE id=? AND state=?', (new, device_id, old))
            if result.rowcount != 1:
                raise ValueError('Invalid VPN device state transition.')

    def devices(self):
        with self._transaction() as connection:
            return [dict(row) for row in connection.execute('SELECT * FROM devices ORDER BY created, id')]

    def authorized_peers(self):
        return tuple(PeerPlan(row['public_key'], row['address']) for row in self.devices() if row['state'] == 'approved')
