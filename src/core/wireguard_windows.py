"""Windows WireGuard service integration using the official secure importer."""

import base64
import ctypes
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

from src.core.vpn_service import managed_tunnel_name, render_server_config, render_client_config
from src.core.vpn_backend import WireGuardError


def _quoted_options(value):
    value = str(value)
    return (f'"{value}"',) if any(c.isspace() for c in value) else (value, f'"{value}"')


def _powershell(script, data):
    preamble = '$ErrorActionPreference="Stop";[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new();$p=[Console]::In.ReadToEnd()|ConvertFrom-Json;'
    encoded = base64.b64encode((preamble + script).encode('utf-16-le')).decode('ascii')
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                                input=json.dumps(data), text=True, encoding='utf-8', errors='replace',
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise WireGuardError('WireGuard Windows operation failed.')
        return json.loads(result.stdout.lstrip('\ufeff')) if result.stdout.strip() else None
    except (subprocess.SubprocessError, ValueError):
        raise WireGuardError('WireGuard Windows operation failed.') from None


def _admin():
    return sys.platform == 'win32' and bool(ctypes.windll.shell32.IsUserAnAdmin())


def installed_directory():
    # Do not use an elevated process's overridable ProgramFiles environment.
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x26, None, 0, buffer) != 0:
        raise WireGuardError('Could not locate the Windows Program Files directory.')
    return Path(buffer.value) / 'WireGuard'


def verify_binaries(directory):
    paths = [Path(directory) / name for name in ('wireguard.exe', 'wg.exe')]
    if not all(path.is_file() for path in paths):
        raise WireGuardError('Install the official WireGuard for Windows first.')
    result = _powershell('''
        @($p.paths | ForEach-Object {
            $s=Get-AuthenticodeSignature -LiteralPath $_;
            [pscustomobject]@{valid=($s.Status -eq 'Valid');publisher=if($s.SignerCertificate){$s.SignerCertificate.GetNameInfo('SimpleName',$false)}else{''}}
        }) | ConvertTo-Json -Compress
    ''', {'paths': [str(path) for path in paths]})
    if not isinstance(result, list) or len(result) != 2 or any(
        item.get('valid') is not True or item.get('publisher') != 'WireGuard LLC' for item in result
    ):
        raise WireGuardError('WireGuard binary signature verification failed.')
    return {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def existing_routes(exclude_interface=None):
    routes = _powershell('''
        @(Get-NetRoute -AddressFamily IPv4 | Where-Object {
            $_.DestinationPrefix -ne '0.0.0.0/0' -and $_.InterfaceAlias -ne $p.exclude
        } | Select-Object -ExpandProperty DestinationPrefix -Unique) | ConvertTo-Json -Compress
    ''', {'exclude': exclude_interface})
    if routes is None:
        raise WireGuardError('Could not inspect Windows network routes.')
    routes = [routes] if isinstance(routes, str) else routes
    # /32 host entries and multicast routes cannot invalidate unrelated networks.
    return tuple(str(ipaddress.ip_network(route, strict=False)) for route in routes)


class WindowsWireGuard:
    """Requires an elevated app and an existing official installation.

    The official manager receives a short-lived ACL-restricted .conf, converts
    it to SYSTEM DPAPI and deletes the plaintext. No private keys in argv/logs.
    Only app-namespaced services with a verified executable/path are managed.
    """

    def __init__(self):
        if sys.platform != 'win32':
            raise WireGuardError('WireGuard tunnel integration currently requires Windows.')
        if not _admin():
            raise WireGuardError('Run ServerPy as administrator to manage WireGuard tunnels.')
        self.directory = installed_directory().resolve()
        self.hashes = verify_binaries(self.directory)
        self.config_directory = self.directory / 'Data/Configurations'

    def _run(self, executable, arguments, *, allow_failure=False):
        path = self.directory / executable
        if path not in self.hashes or hashlib.sha256(path.read_bytes()).hexdigest() != self.hashes[path]:
            raise WireGuardError('WireGuard binaries changed. Reopen the tunnel controls.')
        try:
            result = subprocess.run([str(path), *arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding='utf-8', errors='replace', timeout=20,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.SubprocessError:
            raise WireGuardError('WireGuard command did not finish successfully.') from None
        if result.returncode and not allow_failure:
            raise WireGuardError('WireGuard command failed.')
        return result.returncode, result.stdout

    def _service(self, name):
        result = _powershell('''
            $s=Get-CimInstance Win32_Service -Filter ("Name='"+$p.name+"'");
            if($s){[pscustomobject]@{state=$s.State;path=$s.PathName}|ConvertTo-Json -Compress}else{'null'}
        ''', {'name': name})
        return result

    def _owned_service(self, name):
        if not name.startswith('serverpy-') or len(name) != 25:
            raise ValueError('Invalid managed WireGuard tunnel name.')
        managed_tunnel_name(name[9:])
        service = self._service(f'WireGuardTunnel${name}')
        if service is not None:
            # Match only the exact executable, service switch and encrypted path.
            valid = {f'{exe} /tunnelservice {config}'.casefold()
                     for exe in _quoted_options(self.directory / 'wireguard.exe')
                     for config in _quoted_options(self.config_directory / (name + '.conf.dpapi'))}
            if service['path'].casefold() not in valid:
                raise WireGuardError('Existing WireGuard service is not owned by this app.')
        return service

    def _wait_service(self, name, running):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            service = self._owned_service(name)
            if (running and service and service['state'] == 'Running') or (not running and service is None):
                return
            time.sleep(0.2)
        raise WireGuardError('WireGuard service did not reach the requested state.')

    def stop(self, name):
        service = self._owned_service(name)
        if service:
            self._run('wireguard.exe', ['/uninstalltunnelservice', name])
            self._wait_service(name, False)

    def _ensure_manager(self):
        manager = self._service('WireGuardManager')
        valid = {f'{exe} /managerservice'.casefold() for exe in _quoted_options(self.directory / 'wireguard.exe')}
        if manager and manager['path'].casefold() not in valid:
            raise WireGuardError('Unexpected WireGuard manager service.')
        if manager is None or manager['state'] != 'Running':
            if manager is None:
                self._run('wireguard.exe', ['/installmanagerservice'])
            else:
                _powershell('Start-Service -Name WireGuardManager', {})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.config_directory.is_dir() and (self._service('WireGuardManager') or {}).get('state') == 'Running':
                return
            time.sleep(0.2)
        raise WireGuardError('WireGuard secure configuration importer is unavailable.')

    def _import(self, name, config):
        encrypted = self.config_directory / f'{name}.conf.dpapi'
        plain = self.config_directory / f'{name}.conf'
        temporary = self.config_directory / f'{name}-{secrets.token_hex(8)}.tmp'
        if plain.exists():
            raise WireGuardError('A pending WireGuard import already exists. Inspect it before retrying.')
        if encrypted.exists():
            encrypted.unlink()  # Only after the owned tunnel has been stopped.
        try:
            _powershell('''
                $acl=[System.Security.AccessControl.FileSecurity]::new();
                $acl.SetSecurityDescriptorSddlForm('D:P(A;;FA;;;SY)(A;;FA;;;BA)');
                $fs=[System.IO.File]::Create($p.path,4096,[System.IO.FileOptions]::None,$acl);
                try{$bytes=[System.Text.Encoding]::UTF8.GetBytes($p.config);$fs.Write($bytes,0,$bytes.Length);$fs.Flush($true)}finally{$fs.Dispose()}
            ''', {'path': str(temporary), 'config': config})
            temporary.rename(plain)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if encrypted.exists() and not plain.exists():
                    return encrypted
                time.sleep(0.2)
            raise WireGuardError('WireGuard did not protect the tunnel configuration.')
        finally:
            temporary.unlink(missing_ok=True)
            plain.unlink(missing_ok=True)

    def _start(self, name, config):
        self._owned_service(name)
        self.stop(name)
        self._ensure_manager()
        path = self._import(name, config)
        try:
            self._run('wireguard.exe', ['/installtunnelservice', str(path)])
            _powershell('Set-Service -Name $p.name -StartupType Manual', {'name': f'WireGuardTunnel${name}'})
            self._wait_service(name, True)
            return self.status(name)
        except BaseException:
            self.stop(name)
            raise

    def start_server(self, identity, cidr, port, peers):
        name = managed_tunnel_name(hashlib.sha256(('server:' + identity.public_key).encode()).hexdigest()[:16])
        config = render_server_config(identity, cidr, port, peers, existing_routes(name))
        return self._start(name, config)

    def start_client(self, identity, connection):
        name = managed_tunnel_name(hashlib.sha256(('client:' + connection.server_public_key).encode()).hexdigest()[:16])
        config = render_client_config(identity, connection, existing_routes(name))
        return self._start(name, config)

    def status(self, name):
        service = self._owned_service(name)
        result = {'name': name, 'service_running': bool(service and service['state'] == 'Running'), 'handshake_verified': False}
        if result['service_running']:
            code, output = self._run('wg.exe', ['show', name, 'latest-handshakes'], allow_failure=True)
            if code == 0:
                timestamps = []
                for line in output.splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1].isdigit():
                        timestamps.append(int(parts[1]))
                result['handshake_verified'] = any(0 <= time.time() - stamp <= 180 for stamp in timestamps if stamp)
        return result
