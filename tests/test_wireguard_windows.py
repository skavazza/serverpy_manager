import hashlib
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from src.core.vpn import generate_identity, PeerPlan
from src.core.vpn_service import ClientConnection, render_client_config, managed_tunnel_name
from src.core.wireguard_windows import WindowsWireGuard, WireGuardError, verify_binaries


class FakeWireGuard(WindowsWireGuard):
    """Service simulation only; never creates adapters or invokes Windows tools."""
    def __init__(self, root):
        self.directory = Path(root)
        self.config_directory = self.directory / 'Data/Configurations'
        self.states = {}
        self.calls = []
        self.configs = []
        self.fail_install = False
        self.handshake = 0

    def _service(self, name):
        return self.states.get(name)

    def _ensure_manager(self):
        pass

    def _import(self, name, config):
        self.configs.append(config)
        return self.config_directory / f'{name}.conf.dpapi'

    def _run(self, executable, arguments, **kwargs):
        self.calls.append((executable, arguments))
        if arguments[0] == '/installtunnelservice':
            name = Path(arguments[1]).name.removesuffix('.conf.dpapi')
            self.states[f'WireGuardTunnel${name}'] = {
                'state': 'Running',
                'path': f'"{self.directory / "wireguard.exe"}" /tunnelservice "{arguments[1]}"',
            }
            if self.fail_install:
                raise WireGuardError('WireGuard command failed.')
        elif arguments[0] == '/uninstalltunnelservice':
            self.states.pop(f'WireGuardTunnel${arguments[1]}', None)
        elif arguments[0] == 'show':
            return 0, f'public-key\t{self.handshake}\n'
        return 0, ''


class TestWireGuardIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = FakeWireGuard(self.temp.name)
        self.server = generate_identity()
        self.client = generate_identity()
        self.profile = ClientConnection('10.77.0.0/24', '10.77.0.2', self.client.public_key, self.server.public_key, 'vpn.example.com', 51820)

    def test_public_profile_roundtrip_and_client_config_have_only_server_host_route(self):
        parsed = ClientConnection.parse(self.profile.export())
        self.assertNotIn(self.client.private_key, self.profile.export())
        self.assertNotIn(self.server.private_key, self.profile.export())
        config = render_client_config(self.client, parsed)
        self.assertIn('Address = 10.77.0.2/32', config)
        self.assertIn('AllowedIPs = 10.77.0.1/32', config)
        self.assertIn('PersistentKeepalive = 25', config)
        self.assertNotIn('0.0.0.0/0', config)
        self.assertNotIn('DNS', config)

    def test_profile_rejects_self_invalid_address_injection_and_wrong_client(self):
        from dataclasses import replace
        for profile in (
            replace(self.profile, address='10.77.0.1'),
            replace(self.profile, address='10.77.0.255'),
            replace(self.profile, host='vpn\nPostUp=cmd'),
            replace(self.profile, cidr='0.0.0.0/0'),
            replace(self.profile, address=123),
            replace(self.profile, client_public_key=self.server.public_key),
        ):
            with self.assertRaises(ValueError):
                profile.validate()
        with self.assertRaises(ValueError):
            render_client_config(generate_identity(), self.profile)
        with self.assertRaises(ValueError):
            ClientConnection.parse(self.profile.export()[:-1] + ',"port":1234}')

    def test_server_start_stop_simulation_and_no_private_key_in_commands(self):
        with patch('src.core.wireguard_windows.existing_routes', return_value=()), patch('src.core.wireguard_windows._powershell'):
            status = self.runtime.start_server(self.server, '10.77.0.0/24', 51820, (PeerPlan(self.client.public_key, '10.77.0.2'),))
        self.assertTrue(status['service_running'])
        self.assertFalse(status['handshake_verified'])
        self.assertIn('AllowedIPs = 10.77.0.2/32', self.runtime.configs[0])
        self.assertNotIn(self.server.private_key, str(self.runtime.calls))
        self.runtime.stop(status['name'])
        self.assertFalse(self.runtime.status(status['name'])['service_running'])

    def test_client_start_and_handshake_distinct_from_running_service(self):
        with patch('src.core.wireguard_windows.existing_routes', return_value=()), patch('src.core.wireguard_windows._powershell'):
            status = self.runtime.start_client(self.client, self.profile)
        self.assertFalse(status['handshake_verified'])
        self.runtime.handshake = int(time.time())
        self.assertTrue(self.runtime.status(status['name'])['handshake_verified'])
        self.runtime.handshake = int(time.time()) - 181
        self.assertFalse(self.runtime.status(status['name'])['handshake_verified'])

    def test_failed_install_rolls_back_its_own_service(self):
        self.runtime.fail_install = True
        with patch('src.core.wireguard_windows.existing_routes', return_value=()), patch('src.core.wireguard_windows._powershell'):
            with self.assertRaises(WireGuardError):
                self.runtime.start_client(self.client, self.profile)
        self.assertEqual(self.runtime.states, {})

    def test_foreign_service_is_never_removed(self):
        name = managed_tunnel_name('abcdef0123456789')
        self.runtime.states[f'WireGuardTunnel${name}'] = {'state': 'Running', 'path': 'other.exe /tunnelservice other.conf'}
        with self.assertRaises(WireGuardError):
            self.runtime.stop(name)
        self.assertEqual(self.runtime.calls, [])
        with self.assertRaises(ValueError):
            self.runtime.stop('WireGuardManager')

    def test_network_conflict_fails_before_any_service_command(self):
        with patch('src.core.wireguard_windows.existing_routes', return_value=('10.77.0.0/16',)):
            with self.assertRaises(ValueError):
                self.runtime.start_client(self.client, self.profile)
        self.assertEqual(self.runtime.calls, [])

    def test_unsigned_or_wrong_publisher_binaries_are_rejected(self):
        for name in ('wireguard.exe', 'wg.exe'):
            (Path(self.temp.name) / name).write_bytes(b'test-only')
        for signature in ({'valid': False, 'publisher': 'WireGuard LLC'}, {'valid': True, 'publisher': 'Other publisher'}):
            with patch('src.core.wireguard_windows._powershell', return_value=[signature, signature]), self.assertRaises(WireGuardError):
                verify_binaries(self.temp.name)

    def test_modified_executable_never_runs(self):
        runtime = WindowsWireGuard.__new__(WindowsWireGuard)
        runtime.directory = Path(self.temp.name)
        path = runtime.directory / 'wg.exe'
        path.write_bytes(b'original')
        runtime.hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest()}
        path.write_bytes(b'modified')
        with patch('src.core.wireguard_windows.subprocess.run') as run, self.assertRaises(WireGuardError):
            runtime._run('wg.exe', ['show'])
        run.assert_not_called()

    def test_missing_administration_is_reported_without_commands(self):
        with patch('src.core.wireguard_windows.sys.platform', 'win32'), patch('src.core.wireguard_windows._admin', return_value=False), patch('src.core.wireguard_windows.subprocess.run') as run:
            with self.assertRaisesRegex(WireGuardError, 'administrator'):
                WindowsWireGuard()
        run.assert_not_called()

    def test_import_timeout_cleans_up_plaintext_and_staging_file(self):
        runtime = self.runtime
        runtime.config_directory.mkdir(parents=True)
        name = managed_tunnel_name('abcdef0123456789')
        def stage(script, data):
            Path(data['path']).write_text('test fixture, not a private key')
        with patch('src.core.wireguard_windows._powershell', side_effect=stage), patch('src.core.wireguard_windows.time.monotonic', side_effect=(0, 16)):
            with self.assertRaises(WireGuardError):
                WindowsWireGuard._import(runtime, name, 'test fixture')
        self.assertEqual(list(runtime.config_directory.iterdir()), [])

    def test_successful_import_requires_encryption_and_plaintext_removal(self):
        runtime = self.runtime
        runtime.config_directory.mkdir(parents=True)
        name = managed_tunnel_name('abcdef0123456789')
        plain = runtime.config_directory / f'{name}.conf'
        encrypted = runtime.config_directory / f'{name}.conf.dpapi'
        def stage(script, data):
            Path(data['path']).write_text('test fixture')
        def migrate(_):
            encrypted.write_bytes(b'protected fixture')
            plain.unlink()
        with patch('src.core.wireguard_windows._powershell', side_effect=stage), patch('src.core.wireguard_windows.time.sleep', side_effect=migrate):
            self.assertEqual(WindowsWireGuard._import(runtime, name, 'test fixture'), encrypted)
        self.assertEqual(list(runtime.config_directory.iterdir()), [encrypted])


if __name__ == '__main__':
    unittest.main()
