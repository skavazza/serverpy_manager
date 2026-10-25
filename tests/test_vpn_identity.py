import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.core.vpn import generate_identity, PeerPlan, WireGuardIdentity
from src.core.vpn_identity import WindowsIdentityStore, validate_identity
from src.core.vpn_service import plan_tunnel_service, render_server_config


@unittest.skipUnless(sys.platform == 'win32', 'Requires real Windows DPAPI')
class TestWindowsVPNIdentity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = WindowsIdentityStore(self.temp.name)

    def test_real_dpapi_roundtrip_ciphertext_and_no_replacement(self):
        identity = self.store.create('device')
        self.assertEqual(self.store.load('device'), identity)
        encrypted = next(Path(self.temp.name).iterdir()).read_bytes()
        self.assertNotIn(identity.private_key.encode(), encrypted)
        self.assertNotIn(base64.b64decode(identity.private_key), encrypted)
        with self.assertRaises(FileExistsError):
            self.store.create('device')
        self.assertEqual(self.store.load('device'), identity)
        self.assertEqual(len(list(Path(self.temp.name).iterdir())), 1)

    def test_corruption_fails_closed_without_rotating_identity(self):
        self.store.create('device')
        path = next(Path(self.temp.name).iterdir())
        encrypted = path.read_bytes()
        damaged = encrypted[:-10] + bytes(10)
        path.write_bytes(damaged)
        with self.assertRaises(OSError):
            self.store.load('device')
        self.assertEqual(path.read_bytes(), damaged)

    def test_concurrent_create_keeps_single_identity(self):
        def create():
            try:
                return self.store.create('device')
            except FileExistsError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            identities = [item for item in pool.map(lambda _: create(), range(4)) if item]
        self.assertEqual(len(identities), 1)
        self.assertEqual(self.store.load('device'), identities[0])

    def test_failed_publication_leaves_no_partial_file(self):
        with patch('src.core.vpn_identity.os.link', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.store.create('device')
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_names_cannot_escape_store_or_use_reserved_devices(self):
        for name in ('../device', 'x\\device', 'x\n', 'CON', 'con', 'nul', 'lpt1', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.create(name)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_copying_ciphertext_under_another_identity_is_rejected(self):
        self.store.create('original')
        original = next(Path(self.temp.name).iterdir())
        (Path(self.temp.name) / 'other.identity.dpapi').write_bytes(original.read_bytes())
        with self.assertRaises(ValueError):
            self.store.load('other')

    def test_encryption_failure_does_not_write_any_files(self):
        with patch('src.core.vpn_identity._dpapi', side_effect=OSError('protection failed')):
            with self.assertRaises(OSError):
                self.store.create('device')
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])


class TestVPNServicePlanning(unittest.TestCase):
    def test_mismatched_key_pair_is_rejected(self):
        alice, bob = generate_identity(), generate_identity()
        with self.assertRaises(ValueError):
            validate_identity(WireGuardIdentity(alice.private_key, bob.public_key))

    def test_service_plan_cannot_target_arbitrary_service_names(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = plan_tunnel_service(directory, 'abcdef0123456789')
            self.assertEqual(plan.service_name, 'WireGuardTunnel$serverpy-abcdef0123456789')
            self.assertTrue(str(plan.config_path).endswith('.conf.dpapi'))
            self.assertEqual(plan.install_arguments[0], '/installtunnelservice')
            self.assertEqual(plan.uninstall_arguments, ('/uninstalltunnelservice', plan.tunnel_name))
            for invalid in ('../other', 'WireGuardManager', 'x\nPostUp=cmd', ''):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    plan_tunnel_service(directory, invalid)
        with self.assertRaises(ValueError):
            plan_tunnel_service('relative', 'abcdef0123456789')

    def test_full_network_config_has_only_authorized_host_routes(self):
        identity = generate_identity()
        peers = [PeerPlan(generate_identity().public_key, f'10.77.0.{i}') for i in range(2, 7)]
        config = render_server_config(identity, '10.77.0.0/29', 51820, peers)
        self.assertIn('Address = 10.77.0.1/29', config)
        self.assertEqual(config.count('AllowedIPs = '), 5)
        for peer in peers:
            self.assertIn(f'AllowedIPs = {peer.address}/32', config)
        for forbidden in ('PostUp', 'PreUp', 'DNS', '0.0.0.0/0'):
            self.assertNotIn(forbidden, config)

    def test_render_rejects_self_duplicate_and_injected_peers(self):
        identity = generate_identity()
        peer = PeerPlan(generate_identity().public_key, '10.77.0.2')
        for peers in ([PeerPlan(identity.public_key, '10.77.0.2')], [peer, peer],
                      [PeerPlan(peer.public_key, '10.77.0.2\nPostUp=cmd')]):
            with self.subTest(peers=peers), self.assertRaises(ValueError):
                render_server_config(identity, '10.77.0.0/29', 51820, peers)

    def test_unsupported_platform_fails_before_storage(self):
        with patch('src.core.vpn_identity.sys.platform', 'linux'):
            with self.assertRaises(OSError):
                WindowsIdentityStore()


if __name__ == '__main__':
    unittest.main()
