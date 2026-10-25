"""Verified download and UAC launch for the official WireGuard MSI."""

import ctypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

from .vpn_backend import WireGuardError
from .wireguard_windows import _powershell


_INSTALLER_VERSION = '1.1.1'
_INSTALLER_URL = (
    f'https://download.wireguard.com/windows-client/'
    f'wireguard-amd64-{_INSTALLER_VERSION}.msi'
)
_INSTALLER_SHA256 = '7bfed60ad61b785c914b38b61555a975488e1d3ec472dbfb2fcdf498fca75242'
_MAX_INSTALLER_SIZE = 20 * 1024 * 1024
_INSTALLER_NAME = f'wireguard-amd64-{_INSTALLER_VERSION}.msi'


def wireguard_install_supported():
    return sys.platform == 'win32'


def _installer_path():
    local_app_data = Path(
        os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')
    )
    return local_app_data / 'ServerPy' / 'HTTPManager' / 'wireguard' / _INSTALLER_NAME


def _verify_installer(path):
    if path.stat().st_size > _MAX_INSTALLER_SIZE:
        raise WireGuardError('The WireGuard installer exceeds the size limit.')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != _INSTALLER_SHA256:
        raise WireGuardError('WireGuard installer SHA-256 verification failed.')
    signature = _powershell('''
        $s=Get-AuthenticodeSignature -LiteralPath $p.path;
        [pscustomobject]@{
            valid=($s.Status -eq 'Valid');
            publisher=if($s.SignerCertificate){$s.SignerCertificate.GetNameInfo('SimpleName',$false)}else{''}
        } | ConvertTo-Json -Compress
    ''', {'path': str(path)})
    if (
        not isinstance(signature, dict)
        or signature.get('valid') is not True
        or signature.get('publisher') != 'WireGuard LLC'
    ):
        raise WireGuardError('WireGuard installer signature verification failed.')


def _download_installer(destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.parent.is_symlink():
        raise WireGuardError('WireGuard installer storage must not be a symbolic link.')
    descriptor, temporary_name = tempfile.mkstemp(
        prefix='.wireguard-installer-', suffix='.msi', dir=destination.parent,
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    downloaded = 0
    try:
        try:
            with os.fdopen(descriptor, 'wb') as installer:
                with urllib.request.urlopen(_INSTALLER_URL, timeout=30) as response:
                    content_length = response.headers.get('Content-Length')
                    total = int(content_length) if content_length and content_length.isdigit() else 0
                    if total > _MAX_INSTALLER_SIZE:
                        raise WireGuardError('The WireGuard installer exceeds the size limit.')
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > _MAX_INSTALLER_SIZE:
                            raise WireGuardError('The WireGuard installer exceeds the size limit.')
                        digest.update(chunk)
                        installer.write(chunk)
        except WireGuardError:
            raise
        except (OSError, ValueError) as error:
            raise WireGuardError('Unable to download the official WireGuard installer.') from error
        if digest.hexdigest() != _INSTALLER_SHA256:
            raise WireGuardError('WireGuard installer SHA-256 verification failed.')
        _verify_installer(temporary)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _verified_installer():
    destination = _installer_path()
    if destination.is_symlink():
        raise WireGuardError('WireGuard installer storage must not be a symbolic link.')
    if destination.is_file():
        _verify_installer(destination)
    else:
        _download_installer(destination)
    return destination


def _system_directory():
    buffer = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not size or size >= len(buffer):
        raise WireGuardError('Could not locate the Windows system directory.')
    return Path(buffer.value)


def _launch_installer(installer):
    executable = _system_directory() / 'msiexec.exe'
    arguments = subprocess.list2cmdline(['/i', str(installer), '/passive', '/norestart'])
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None, 'runas', str(executable), arguments, None, 1,
        )
    except (AttributeError, OSError) as error:
        raise WireGuardError(
            'Unable to start the WireGuard installer with administrator approval.'
        ) from error
    if result <= 32:
        if result == 1223:
            raise WireGuardError('WireGuard installation was cancelled in the administrator prompt.')
        raise WireGuardError(
            'Unable to start the WireGuard installer with administrator approval.'
        )


def install_wireguard():
    """Download a pinned official MSI and launch it through the Windows UAC prompt."""
    if not wireguard_install_supported():
        raise WireGuardError('Automatic WireGuard installation is available on Windows only.')
    installer = _verified_installer()
    _launch_installer(installer)
    return str(installer)
