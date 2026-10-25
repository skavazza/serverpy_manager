"""WireGuard planning primitives and read-only prerequisite diagnostics."""

import base64
import ctypes
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption


@dataclass(frozen=True)
class WireGuardIdentity:
    private_key: str = field(repr=False)
    public_key: str


def generate_identity():
    """Generate in memory only; callers must protect any future persistence."""
    key = X25519PrivateKey.generate()
    private = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return WireGuardIdentity(
        base64.b64encode(private).decode('ascii'),
        base64.b64encode(public).decode('ascii'),
    )


def validate_public_key(value):
    """Accept canonical nonzero 32-byte WireGuard public keys only."""
    try:
        raw = base64.b64decode(value, validate=True)
        canonical = base64.b64encode(raw).decode('ascii')
    except (ValueError, TypeError):
        raise ValueError('Invalid WireGuard public key.') from None
    if len(raw) != 32 or not any(raw) or value != canonical:
        raise ValueError('Invalid WireGuard public key.')
    return value


def validate_endpoint(host, port):
    """Validate structured input without permitting configuration directives."""
    if not isinstance(host, str) or not host or host != host.strip():
        raise ValueError('Enter a hostname or IP address without whitespace.')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or not all(
            re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
            for label in host.split('.')
        ):
            raise ValueError('Invalid endpoint hostname.') from None
        normalized = host.lower()
    else:
        if address.is_unspecified or address.is_multicast or '%' in host:
            raise ValueError('Endpoint must be a unicast address without a zone ID.')
        normalized = f'[{address}]' if address.version == 6 else str(address)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Endpoint port must be between 1 and 65535.')
    return f'{normalized}:{port}'


def validate_network(cidr, existing_networks=()):
    """Initial VPN supports private IPv4 /16 through /29; no default routes."""
    try:
        network = ipaddress.ip_network(cidr, strict=True)
    except ValueError:
        raise ValueError('Enter a valid network address and prefix.') from None
    private_ranges = tuple(ipaddress.ip_network(item) for item in (
        '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16',
    ))
    if network.version != 4 or not 16 <= network.prefixlen <= 29 or not any(
        network.subnet_of(private) for private in private_ranges
    ):
        raise ValueError('Use a private IPv4 network with prefix /16 through /29.')
    for item in existing_networks:
        existing = ipaddress.ip_network(item, strict=False)
        if network.overlaps(existing):
            raise ValueError('VPN network overlaps an existing network.')
    return network


@dataclass(frozen=True)
class PeerPlan:
    public_key: str
    address: str

    @property
    def allowed_ips(self):
        return f'{self.address}/32'


def validate_peer_allocations(network, existing_peers):
    """Check persisted allocations without requiring a free address."""
    used = set()
    keys = set()
    for peer in existing_peers:
        validate_public_key(peer.public_key)
        address = ipaddress.ip_address(peer.address)
        if address.version != 4 or address not in network or int(address) in (
            int(network.network_address), int(network.network_address) + 1,
            int(network.broadcast_address),
        ) or address in used or peer.public_key in keys:
            raise ValueError('Existing peer allocation is invalid or duplicated.')
        used.add(address)
        keys.add(peer.public_key)
    return used, keys


def plan_peer(cidr, public_key, existing_peers=(), existing_networks=()):
    """Allocate a host route, reserving first host for server; no I/O."""
    network = validate_network(cidr, existing_networks)
    public_key = validate_public_key(public_key)
    used, keys = validate_peer_allocations(network, existing_peers)
    if public_key in keys:
        raise ValueError('This device is already registered.')
    for host in network.hosts():
        if int(host) != int(network.network_address) + 1 and host not in used:
            return PeerPlan(public_key, str(host))
    raise ValueError('VPN network has no available participant addresses.')


def wireguard_diagnostics():
    """Read-only prerequisite inspection; never starts services or executables."""
    windows = sys.platform == 'win32'
    install_dir = Path(os.environ.get('ProgramW6432', os.environ.get('ProgramFiles', r'C:\Program Files'))) / 'WireGuard'
    found = {}
    linux = sys.platform.startswith('linux')
    if windows:
        for name in ('wireguard', 'wg'):
            candidate = install_dir / f'{name}.exe'
            found[name] = str(candidate) if candidate.is_file() else None
    elif linux:
        for name, candidates in {
            'wg': ('/usr/bin/wg', '/usr/sbin/wg'),
            'ip': ('/usr/sbin/ip', '/sbin/ip', '/usr/bin/ip'),
            'systemd-creds': ('/usr/bin/systemd-creds',),
        }.items():
            found[name] = next((candidate for candidate in candidates if Path(candidate).is_file()), None)
    elevated = None
    if windows:
        try:
            elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (OSError, AttributeError):
            pass
    elif linux:
        elevated = getattr(os, 'geteuid', lambda: -1)() == 0
    return {
        'platform': sys.platform,
        'windows_integration_target': windows,
        'linux_integration_target': linux,
        'executables': found,
        'administrator': elevated,
        'binaries_found': bool(found) and all(found.values()),
        'binary_trust_verified': False,
        'network_modified': False,
        'live_tunnel_verified': False,
    }


if __name__ == '__main__':
    print(json.dumps(wireguard_diagnostics(), indent=2))
