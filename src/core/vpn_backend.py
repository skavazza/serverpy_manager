"""Platform-neutral VPN contracts and lazy platform selection."""

import sys
from pathlib import Path
from typing import Protocol


class WireGuardError(OSError):
    """A safe, user-facing VPN prerequisite or lifecycle failure."""


class IdentityStore(Protocol):
    directory: object

    def create(self, name): ...
    def load(self, name): ...


class TunnelBackend(Protocol):
    """Status dictionaries retain service_running for GUI compatibility.

    It means SCM Running on Windows, an UP owned interface on Linux; neither
    alone means an authenticated handshake or end-to-end application traffic.
    """
    def start_server(self, identity, cidr, port, peers): ...
    def start_client(self, identity, connection): ...
    def stop(self, name): ...
    def status(self, name): ...


def vpn_platform() -> str:
    if sys.platform == 'win32':
        return 'windows'
    if sys.platform.startswith('linux'):
        return 'linux'
    raise WireGuardError('VPN integration supports Windows and Linux only.')


def identity_store(directory=None) -> IdentityStore:
    if vpn_platform() == 'windows':
        from .vpn_identity import WindowsIdentityStore
        return WindowsIdentityStore(directory)
    from .vpn_linux import LinuxIdentityStore
    return LinuxIdentityStore(directory)


def tunnel_backend() -> TunnelBackend:
    if vpn_platform() == 'windows':
        from .wireguard_windows import WindowsWireGuard
        return WindowsWireGuard()
    from .vpn_linux import LinuxWireGuard
    return LinuxWireGuard()


def vpn_data_directory() -> Path:
    if vpn_platform() == 'windows':
        from .vpn_identity import WindowsIdentityStore
        return WindowsIdentityStore().directory.parent
    return Path('/var/lib/serverpy/vpn')
