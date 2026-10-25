"""User-scoped Windows DPAPI identity storage; never writes plaintext keys."""

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from src.core.vpn import WireGuardIdentity, generate_identity, validate_public_key


class _Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data, *, decrypt=False):
    if sys.platform != 'win32':
        raise OSError('VPN identity protection currently supports Windows only.')
    if not isinstance(data, bytes) or not 0 < len(data) <= 65536:
        raise ValueError('Invalid protected VPN identity size.')
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = _Blob(len(data), buffer)
    output = _Blob()
    # Entropy is an application namespace, not an additional secret.
    entropy_bytes = b'ServerPy.VPN.Identity.v1'
    entropy_buffer = (ctypes.c_ubyte * len(entropy_bytes)).from_buffer_copy(entropy_bytes)
    entropy = _Blob(len(entropy_bytes), entropy_buffer)
    common = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
              ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = common
    operation.restype = wintypes.BOOL
    description = None if decrypt else ctypes.cast(ctypes.c_wchar_p('ServerPy VPN identity'), ctypes.c_void_p)
    try:
        # UI_FORBIDDEN only: intentionally NEVER use LOCAL_MACHINE scope.
        if not operation(ctypes.byref(source), description, ctypes.byref(entropy),
                         None, None, 1, ctypes.byref(output)):
            raise OSError('Windows could not protect or unlock the VPN identity.')
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.memset(buffer, 0, len(data))
        if output.pbData:
            ctypes.memset(output.pbData, 0, output.cbData)
            kernel.LocalFree(output.pbData)


def validate_identity(identity):
    """Ensure a stored public key actually belongs to its private key."""
    validate_public_key(identity.public_key)
    try:
        raw = base64.b64decode(identity.private_key, validate=True)
        if len(raw) != 32 or base64.b64encode(raw).decode('ascii') != identity.private_key:
            raise ValueError
        public = X25519PrivateKey.from_private_bytes(raw).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        if base64.b64encode(public).decode('ascii') != identity.public_key:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('Invalid VPN identity key pair.') from None
    return identity


class WindowsIdentityStore:
    """Create-once encrypted identities. Corruption never silently rotates keys.

    This is user identity storage, NOT a WireGuard .conf.dpapi service file.
    Windows administrators and code running as the same user are trusted.
    """

    def __init__(self, directory=None):
        if sys.platform != 'win32':
            raise OSError('VPN identity storage currently supports Windows only.')
        if directory is None:
            root = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
            directory = root / 'ServerPy' / 'HTTPManager' / 'vpn' / 'identities'
        self.directory = Path(directory)

    def _path(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,47}', name):
            raise ValueError('Invalid VPN identity name.')
        if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}:
            raise ValueError('Invalid VPN identity name.')
        return self.directory / f'{name}.identity.dpapi'

    def create(self, name):
        path = self._path(name)
        identity = generate_identity()
        payload = json.dumps({
            'version': 1, 'name': name, 'private_key': identity.private_key,
            'public_key': identity.public_key,
        }, separators=(',', ':')).encode('utf-8')
        encrypted = _dpapi(payload)
        self.directory.mkdir(parents=True, exist_ok=True)
        # Only ciphertext reaches disk. Hard-link publication is atomic and
        # fails if the identity already exists, including concurrent creators.
        descriptor, temporary = tempfile.mkstemp(prefix='.identity-', dir=self.directory)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, path)
        finally:
            os.unlink(temporary)
        return identity

    def load(self, name):
        path = self._path(name)
        with path.open('rb') as stream:
            encrypted = stream.read(65537)
        if not 0 < len(encrypted) <= 65536:
            raise ValueError('Invalid protected VPN identity size.')
        payload = _dpapi(encrypted, decrypt=True)
        try:
            data = json.loads(payload)
            if (not isinstance(data, dict) or type(data.get('version')) is not int
                    or data['version'] != 1 or data.get('name') != name
                    or set(data) != {'version', 'name', 'private_key', 'public_key'}):
                raise ValueError
            return validate_identity(WireGuardIdentity(data['private_key'], data['public_key']))
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise ValueError('Invalid protected VPN identity contents.') from None
