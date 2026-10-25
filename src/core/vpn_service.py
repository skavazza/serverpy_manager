"""Strict plans for a future privileged WireGuard service helper.

No subprocess execution: signature verification, ACLs, elevation and ownership
tracking must be implemented before these plans can be applied.
"""

from dataclasses import dataclass
from pathlib import Path
import re
import json

from src.core.vpn import validate_network, validate_peer_allocations, validate_endpoint
from src.core.vpn_identity import validate_identity
from src.core.vpn import validate_public_key, PeerPlan
from src.core.vpn_enrollment import _decode


def managed_tunnel_name(network_id):
    if not isinstance(network_id, str) or not re.fullmatch(r'[a-f0-9]{16}', network_id):
        raise ValueError('Invalid managed VPN network ID.')
    return f'serverpy-{network_id}'


@dataclass(frozen=True)
class TunnelServicePlan:
    tunnel_name: str
    config_path: Path

    @property
    def service_name(self):
        return f'WireGuardTunnel${self.tunnel_name}'

    @property
    def install_arguments(self):
        return ('/installtunnelservice', str(self.config_path))

    @property
    def uninstall_arguments(self):
        return ('/uninstalltunnelservice', self.tunnel_name)


def plan_tunnel_service(directory, network_id):
    """Only app-namespaced, encrypted service configuration paths are planned."""
    name = managed_tunnel_name(network_id)
    root = Path(directory)
    if not root.is_absolute():
        raise ValueError('Managed VPN configuration directory must be absolute.')
    return TunnelServicePlan(name, root / f'{name}.conf.dpapi')


def render_server_config(identity, cidr, port, peers=(), existing_networks=()):
    """Render vetted fields in memory only; no hooks, DNS or default routes."""
    validate_identity(identity)
    network = validate_network(cidr, existing_networks)
    validate_endpoint('127.0.0.1', port)
    peers = tuple(peers)
    validate_peer_allocations(network, peers)
    for peer in peers:
        if peer.public_key == identity.public_key:
            raise ValueError('The server cannot register itself as a participant.')
    lines = ['[Interface]', f'PrivateKey = {identity.private_key}',
             f'Address = {network.network_address + 1}/{network.prefixlen}',
             f'ListenPort = {port}']
    for peer in peers:
        lines.extend(['', '[Peer]', f'PublicKey = {peer.public_key}',
                      f'AllowedIPs = {peer.allowed_ips}'])
    return '\n'.join(lines) + '\n'


@dataclass(frozen=True)
class ClientConnection:
    cidr: str
    address: str
    client_public_key: str
    server_public_key: str
    host: str
    port: int

    def validate(self):
        network = validate_network(self.cidr)
        if not isinstance(self.address, str):
            raise ValueError('Invalid VPN client address.')
        validate_public_key(self.client_public_key)
        validate_public_key(self.server_public_key)
        if self.client_public_key == self.server_public_key:
            raise ValueError('Client and server identities must differ.')
        validate_peer_allocations(network, (PeerPlan(self.client_public_key, self.address),))
        validate_endpoint(self.host, self.port)
        return self

    def export(self):
        self.validate()
        return json.dumps({'format': 'serverpy-wireguard-connection', 'version': 1, **self.__dict__}, separators=(',', ':'))

    @classmethod
    def parse(cls, payload):
        data = _decode(payload)
        if (set(data) != {'format', 'version', 'cidr', 'address', 'client_public_key', 'server_public_key', 'host', 'port'}
                or data.pop('format') != 'serverpy-wireguard-connection'
                or type(data.get('version')) is not int or data.pop('version') != 1):
            raise ValueError('Invalid WireGuard connection profile.')
        return cls(**data).validate()


def render_client_config(identity, connection, existing_networks=()):
    validate_identity(identity)
    connection.validate()
    network = validate_network(connection.cidr, existing_networks)
    if identity.public_key != connection.client_public_key:
        raise ValueError('This connection profile belongs to another client.')
    server_address = network.network_address + 1
    return (f'[Interface]\nPrivateKey = {identity.private_key}\nAddress = {connection.address}/32\n'
            f'\n[Peer]\nPublicKey = {connection.server_public_key}\n'
            f'AllowedIPs = {server_address}/32\nEndpoint = {validate_endpoint(connection.host, connection.port)}\n'
            'PersistentKeepalive = 25\n')
