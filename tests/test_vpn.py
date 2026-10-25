import base64
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from src.core.vpn import (
    PeerPlan, generate_identity, plan_peer, validate_endpoint, validate_network,
    validate_public_key, wireguard_diagnostics,
)


class TestVPNPlanning(unittest.TestCase):
    def test_generated_identities_agree_on_shared_secret_and_hide_private_repr(self):
        alice, bob = generate_identity(), generate_identity()
        a = X25519PrivateKey.from_private_bytes(base64.b64decode(alice.private_key))
        b = X25519PrivateKey.from_private_bytes(base64.b64decode(bob.private_key))
        self.assertEqual(
            a.exchange(X25519PublicKey.from_public_bytes(base64.b64decode(bob.public_key))),
            b.exchange(X25519PublicKey.from_public_bytes(base64.b64decode(alice.public_key))),
        )
        self.assertNotEqual(alice.public_key, bob.public_key)
        self.assertNotIn(alice.private_key, repr(alice))

    def test_public_key_rejects_invalid_zero_and_noncanonical_values(self):
        for value in ('secret', '\n', '', base64.b64encode(bytes(32)).decode(), None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_public_key(value)

    def test_endpoint_accepts_dns_and_ipv6(self):
        self.assertEqual(validate_endpoint('VPN.example.com', 51820), 'vpn.example.com:51820')
        self.assertEqual(validate_endpoint('2001:db8::1', 51820), '[2001:db8::1]:51820')

    def test_endpoint_rejects_directives_urls_and_bad_ports(self):
        for host in ('x\nPostUp=cmd', 'https://host', 'x:123', '-bad', 'x y', '0.0.0.0', 'ff02::1'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                validate_endpoint(host, 51820)
        for port in (0, 65536, True, '51820'):
            with self.subTest(port=port), self.assertRaises(ValueError):
                validate_endpoint('host', port)

    def test_network_rejects_global_default_and_overlapping_routes(self):
        for cidr in ('0.0.0.0/0', '8.8.8.0/24', '10.0.0.1/24', '127.0.0.0/24', '10.0.0.0/30', 'fd00::/64'):
            with self.subTest(cidr=cidr), self.assertRaises(ValueError):
                validate_network(cidr)
        with self.assertRaises(ValueError):
            validate_network('10.77.0.0/24', ['10.77.0.5/16'])
        self.assertEqual(str(validate_network('10.77.0.0/24', ['192.168.1.0/24'])), '10.77.0.0/24')

    def test_allocation_reserves_server_and_prevents_duplicate_keys(self):
        key = generate_identity().public_key
        first = plan_peer('10.77.0.0/29', key)
        self.assertEqual(first.address, '10.77.0.2')
        self.assertEqual(first.allowed_ips, '10.77.0.2/32')
        second = plan_peer('10.77.0.0/29', generate_identity().public_key, [first])
        self.assertEqual(second.address, '10.77.0.3')
        with self.assertRaises(ValueError):
            plan_peer('10.77.0.0/29', key, [first])

    def test_allocation_rejects_corrupt_state_and_exhaustion(self):
        key = generate_identity().public_key
        for address in ('10.77.0.0', '10.77.0.1', '10.77.0.7', '10.78.0.2'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                plan_peer('10.77.0.0/29', key, [PeerPlan(key, address)])
        peers = [PeerPlan(generate_identity().public_key, f'10.77.0.{i}') for i in range(2, 7)]
        with self.assertRaises(ValueError):
            plan_peer('10.77.0.0/29', key, peers)
        with self.assertRaises(ValueError):
            plan_peer('10.77.0.0/29', key, [peers[0], peers[0]])

    def test_diagnostics_does_not_execute_binaries_or_claim_tunnel_success(self):
        with patch('src.core.vpn.Path.is_file', return_value=False), patch('subprocess.run') as run:
            result = wireguard_diagnostics()
        run.assert_not_called()
        self.assertFalse(result['binaries_found'])
        self.assertFalse(result['network_modified'])
        self.assertFalse(result['live_tunnel_verified'])
        self.assertFalse(result['binary_trust_verified'])

    def test_diagnostics_requires_official_windows_install_location(self):
        with (
            patch('src.core.vpn.sys.platform', 'win32'),
            patch('src.core.vpn.os.environ', {'ProgramW6432': r'C:\Program Files'}),
            patch('src.core.vpn.Path.is_file', return_value=False),
        ):
            result = wireguard_diagnostics()
        self.assertFalse(result['binaries_found'])
        self.assertEqual(result['executables'], {'wireguard': None, 'wg': None})


if __name__ == '__main__':
    unittest.main()
