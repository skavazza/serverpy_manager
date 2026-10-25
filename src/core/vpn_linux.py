"""Linux credential protection and kernel WireGuard backend (native QA pending).

    Requires root, systemd-creds >= 250 and distribution-installed wg/ip tools.
    No plaintext configuration is persisted: wg receives a sealed memfd.
"""

from contextlib import contextmanager
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

from .vpn import generate_identity, WireGuardIdentity
from .vpn_identity import validate_identity
from .vpn_service import render_server_config, render_client_config
from .vpn_backend import WireGuardError


def require_linux_root():
    if not sys.platform.startswith('linux'):
        raise WireGuardError('Linux VPN integration requires Linux.')
    if os.geteuid() != 0:
        raise WireGuardError('Linux VPN operations require administrative privileges.')


def trusted_binary(candidates):
    for candidate in candidates:
        path = Path(candidate)
        if not path.is_file():
            continue
        path = path.resolve()
        for item in (path, *path.parents):
            metadata = item.stat()
            if metadata.st_uid != 0 or metadata.st_mode & 0o022:
                raise WireGuardError('Linux VPN tools must be root-owned and protected from modification.')
        if not os.access(path, os.X_OK):
            continue
        return path
    raise WireGuardError('Install the Linux WireGuard and systemd credential prerequisites.')


def _run(path, args, *, payload=None, pass_fds=(), allow_failure=False):
    try:
        result = subprocess.run([str(path), *args], input=payload, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=20, pass_fds=pass_fds,
                                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'})
    except (OSError, subprocess.SubprocessError):
        raise WireGuardError('Linux VPN command failed.') from None
    if result.returncode and not allow_failure:
        raise WireGuardError('Linux VPN command failed.')
    return result.returncode, result.stdout


def private_directory(path):
    """Reject symlinks and insecure existing ancestors, rather than chmod them."""
    path = Path(path).absolute()
    for item in reversed((path, *path.parents)):
        if item.is_symlink():
            raise WireGuardError('Linux VPN storage must not use symbolic links.')
        if not item.exists():
            item.mkdir(mode=0o700)
        metadata = item.stat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise WireGuardError('Linux VPN storage must be root-owned and protected.')
    if path.stat().st_mode & 0o077:
        raise WireGuardError('Linux VPN private directory must have mode 0700.')
    return path


def read_private(path, maximum=65536):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o077:
            raise WireGuardError('Linux VPN private files must be root-owned with mode 0600.')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            data = stream.read(maximum + 1)
        if not data or len(data) > maximum:
            raise WireGuardError('Invalid Linux VPN private file size.')
        return data
    finally:
        os.close(descriptor)


def publish_private(path, data):
    path = Path(path)
    descriptor, staging = tempfile.mkstemp(prefix='.vpn-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(staging, path, follow_symlinks=False)
    finally:
        os.unlink(staging)


class LinuxIdentityStore:
    def __init__(self, directory=None):
        require_linux_root()
        self.directory = Path(directory) if directory is not None else Path('/var/lib/serverpy/vpn/identities')
        self.binary = trusted_binary(('/usr/bin/systemd-creds',))

    def _path(self, name):
        if not isinstance(name, str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,47}', name):
            raise ValueError('Invalid VPN identity name.')
        return self.directory / f'{name}.identity.cred'

    def _crypt(self, name, data, decrypt=False):
        options = [f'--name=serverpy-vpn-{name}']
        if not decrypt:
            options.append('--with-key=host')
        return _run(self.binary, [*options, 'decrypt' if decrypt else 'encrypt', '-', '-'], payload=data)[1]

    def create(self, name):
        path = self._path(name)
        identity = generate_identity()
        payload = json.dumps({'version': 1, 'name': name, 'private_key': identity.private_key,
                              'public_key': identity.public_key}, separators=(',', ':')).encode()
        encrypted = self._crypt(name, payload)
        if not encrypted or len(encrypted) > 65536:
            raise WireGuardError('Linux identity encryption failed.')
        private_directory(self.directory)
        publish_private(path, encrypted)
        return identity

    def load(self, name):
        path = self._path(name)
        # A missing directory is a missing identity, not implicit provisioning.
        if not self.directory.exists():
            raise FileNotFoundError(path)
        private_directory(self.directory)
        data = self._crypt(name, read_private(path), decrypt=True)
        try:
            value = json.loads(data)
            if (set(value) != {'version', 'name', 'private_key', 'public_key'}
                    or type(value['version']) is not int or value['version'] != 1 or value['name'] != name):
                raise ValueError
            return validate_identity(WireGuardIdentity(value['private_key'], value['public_key']))
        except (ValueError, TypeError, KeyError):
            raise WireGuardError('Invalid protected Linux VPN identity.') from None


def linux_tunnel_name(role, server_key):
    # Linux IFNAMSIZ allows at most 15 characters (Windows names have 25).
    return 'spwg-' + hashlib.sha256(f'{role}:{server_key}'.encode()).hexdigest()[:10]


class LinuxWireGuard:
    def __init__(self):
        require_linux_root()
        if not hasattr(os, 'memfd_create'):
            raise WireGuardError('Linux VPN requires anonymous memory file support.')
        self.wg = trusted_binary(('/usr/bin/wg', '/usr/sbin/wg'))
        self.ip = trusted_binary(('/usr/sbin/ip', '/sbin/ip', '/usr/bin/ip'))
        self.hashes = {path: hashlib.sha256(path.read_bytes()).digest() for path in (self.wg, self.ip)}
        self.directory = Path('/run/serverpy-wireguard')

    def _command(self, binary, args, **kwargs):
        if hashlib.sha256(binary.read_bytes()).digest() != self.hashes[binary]:
            raise WireGuardError('Linux VPN tools changed. Reopen the app.')
        return _run(binary, args, **kwargs)

    @contextmanager
    def _lock(self):
        import fcntl
        private_directory(self.directory)
        descriptor = os.open(self.directory / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o077:
                raise WireGuardError('Invalid Linux VPN lock file.')
            deadline = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise WireGuardError('Another Linux VPN operation is in progress.') from None
                    time.sleep(0.05)
            yield
        finally:
            os.close(descriptor)

    def _marker(self, name):
        if not isinstance(name, str) or not re.fullmatch('spwg-[a-f0-9]{10}', name):
            raise ValueError('Invalid managed Linux VPN interface.')
        return self.directory / f'{name}.json'

    def _interface(self, name):
        self._marker(name)
        _, output = self._command(self.ip, ['-json', '-details', 'link', 'show'])
        return next((item for item in json.loads(output) if item['ifname'] == name), None)

    def _owned(self, name):
        interface = self._interface(name)
        if interface is not None:
            marker = json.loads(read_private(self._marker(name), 2048))
            _, key = self._command(self.wg, ['show', name, 'public-key'])
            if (interface.get('ifalias') != f'serverpy-vpn:{name}'
                    or interface.get('linkinfo', {}).get('info_kind') != 'wireguard'
                    or key.decode().strip() != marker['public_key']):
                raise WireGuardError('Existing Linux interface is not owned by this app.')
        return interface

    def _stop(self, name):
        if self._owned(name) is not None:
            self._command(self.ip, ['link', 'delete', 'dev', name])
        self._marker(name).unlink(missing_ok=True)

    def stop(self, name):
        with self._lock():
            self._stop(name)

    def _routes(self, name):
        _, output = self._command(self.ip, ['-json', '-4', 'route', 'show', 'table', 'all'])
        return tuple(str(ipaddress.ip_network(item['dst'], strict=False))
                     for item in json.loads(output)
                     if item.get('dst') not in (None, 'default', '0.0.0.0/0') and item.get('dev') != name)

    def _install(self, name, identity, config, client_route=None):
        self._stop(name)
        publish_private(self._marker(name), json.dumps({'public_key': identity.public_key}).encode())
        created = False
        try:
            self._command(self.ip, ['link', 'add', 'dev', name, 'type', 'wireguard'])
            created = True
            self._command(self.ip, ['link', 'set', 'dev', name, 'alias', f'serverpy-vpn:{name}'])
            lines = config.splitlines()
            addresses = [line.split('=', 1)[1].strip() for line in lines if line.startswith('Address = ')]
            stripped = '\n'.join(line for line in lines if not line.startswith('Address = ')) + '\n'
            import fcntl
            descriptor = os.memfd_create('serverpy-wireguard', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            try:
                with os.fdopen(os.dup(descriptor), 'wb') as stream:
                    stream.write(stripped.encode())
                    stream.flush()
                os.lseek(descriptor, 0, os.SEEK_SET)
                fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
                self._command(self.wg, ['setconf', name, f'/proc/self/fd/{descriptor}'], pass_fds=(descriptor,))
            finally:
                os.close(descriptor)
            for address in addresses:
                self._command(self.ip, ['address', 'add', address, 'dev', name])
            self._command(self.ip, ['link', 'set', 'dev', name, 'up'])
            if client_route:
                self._command(self.ip, ['route', 'add', client_route, 'dev', name])
            return self._status(name)
        except BaseException:
            if created:
                self._command(self.ip, ['link', 'delete', 'dev', name])
            self._marker(name).unlink(missing_ok=True)
            raise

    def start_server(self, identity, cidr, port, peers):
        name = linux_tunnel_name('server', identity.public_key)
        with self._lock():
            config = render_server_config(identity, cidr, port, peers, self._routes(name))
            return self._install(name, identity, config)

    def start_client(self, identity, connection):
        name = linux_tunnel_name('client', connection.server_public_key)
        with self._lock():
            config = render_client_config(identity, connection, self._routes(name))
            route = f'{ipaddress.ip_network(connection.cidr).network_address + 1}/32'
            return self._install(name, identity, config, route)

    def _status(self, name):
        interface = self._owned(name)
        result = {'name': name, 'service_running': bool(interface and 'UP' in interface.get('flags', [])), 'handshake_verified': False}
        if interface:
            _, output = self._command(self.wg, ['show', name, 'latest-handshakes'])
            timestamps = [int(line.split()[1]) for line in output.decode().splitlines()
                          if len(line.split()) == 2 and line.split()[1].isdigit()]
            result['handshake_verified'] = any(0 <= time.time() - value <= 180 for value in timestamps if value)
        return result

    def status(self, name):
        with self._lock():
            return self._status(name)
