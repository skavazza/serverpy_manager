from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from src.core.vpn import generate_identity
from src.core.vpn_registry import VPNRegistry


class TestVPNRegistry(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'registry.sqlite'
        self.now = 1000
        self.server = generate_identity()
        self.registry = self.open_registry()

    def open_registry(self):
        return VPNRegistry(self.path, '10.77.0.0/29', self.server.public_key, clock=lambda: self.now)

    def request(self):
        invite = self.registry.create_invite()
        key = generate_identity().public_key
        return self.registry.request_admission(invite.token, key, 'Notebook')

    def test_invite_has_no_secret_in_repr_or_database_and_requires_approval(self):
        invite = self.registry.create_invite()
        self.assertNotIn(invite.token, repr(invite))
        self.assertNotIn(invite.token.encode(), self.path.read_bytes())
        key = generate_identity().public_key
        device = self.registry.request_admission(invite.token, key, 'Notebook')
        self.assertEqual(self.registry.authorized_peers(), ())
        peer = self.registry.approve(device)
        self.assertEqual(peer.address, '10.77.0.2')
        self.assertEqual(self.open_registry().authorized_peers(), (peer,))
        with self.assertRaises(ValueError):
            self.registry.request_admission(invite.token, generate_identity().public_key, 'Other')

    def test_expiry_revocation_unknown_and_invalid_tokens_fail_closed(self):
        expired = self.registry.create_invite(ttl=60)
        revoked = self.registry.create_invite()
        self.registry.revoke_invite(revoked.token)
        self.now += 60
        for token in (expired.token, revoked.token, 'a' * 43, 'bad\n', None):
            with self.subTest(token=token), self.assertRaises(ValueError):
                self.registry.request_admission(token, generate_identity().public_key, 'Device')
        self.assertEqual(self.registry.devices(), [])

    def test_only_one_concurrent_request_can_consume_invite(self):
        invite = self.registry.create_invite()
        def submit(_):
            try:
                return self.open_registry().request_admission(invite.token, generate_identity().public_key, 'Device')
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(submit, range(4)))
        self.assertEqual(sum(item is not None for item in results), 1)
        self.assertEqual(len(self.registry.devices()), 1)

    def test_concurrent_approval_assigns_distinct_addresses(self):
        devices = [self.request() for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            peers = list(pool.map(lambda device: self.open_registry().approve(device), devices))
        self.assertEqual(len({peer.address for peer in peers}), 4)

    def test_revocation_survives_restart_and_blocks_reregistration(self):
        device = self.request()
        peer = self.registry.approve(device)
        self.registry.revoke(device)
        restarted = self.open_registry()
        self.assertEqual(restarted.authorized_peers(), ())
        with self.assertRaises(ValueError):
            restarted.approve(device)
        invite = restarted.create_invite()
        with self.assertRaises(ValueError):
            restarted.request_admission(invite.token, peer.public_key, 'Again')
        other = restarted.approve(self.request())
        self.assertEqual(other.address, '10.77.0.3')

    def test_rejection_does_not_allow_later_approval(self):
        device = self.request()
        self.registry.reject(device)
        with self.assertRaises(ValueError):
            self.registry.approve(device)
        with self.assertRaises(ValueError):
            self.registry.revoke(device)

    def test_failed_validation_does_not_consume_invite(self):
        invite = self.registry.create_invite()
        for key, name in ((self.server.public_key, 'Server'), ('invalid', 'Device'),
                          (generate_identity().public_key, 'x\nPostUp=cmd')):
            with self.assertRaises(ValueError):
                self.registry.request_admission(invite.token, key, name)
        self.registry.request_admission(invite.token, generate_identity().public_key, 'Valid')

    def test_full_network_approval_rolls_back_and_preserves_pending_request(self):
        for _ in range(5):
            self.registry.approve(self.request())
        pending = self.request()
        with self.assertRaises(ValueError):
            self.registry.approve(pending)
        self.assertEqual(next(row for row in self.registry.devices() if row['id'] == pending)['state'], 'pending')

    def test_registry_cannot_be_reopened_with_different_identity_or_network(self):
        for cidr, key in (('10.78.0.0/29', self.server.public_key), ('10.77.0.0/29', generate_identity().public_key)):
            with self.assertRaises(ValueError):
                VPNRegistry(self.path, cidr, key)
        self.assertEqual(self.open_registry().devices(), [])

    def test_lifetime_and_active_invite_capacity_are_bounded(self):
        for ttl in (0, 59, 86401, True, '900'):
            with self.assertRaises(ValueError):
                self.registry.create_invite(ttl)
        for _ in range(100):
            self.registry.create_invite(ttl=60)
        with self.assertRaises(ValueError):
            self.registry.create_invite()
        self.now += 60
        self.registry.create_invite()


if __name__ == '__main__':
    unittest.main()
