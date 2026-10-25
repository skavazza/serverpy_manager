from contextlib import ExitStack, contextmanager, nullcontext
import io
import json
from pathlib import Path
import stat
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.core.vpn import generate_identity, PeerPlan
from src.core.vpn_service import ClientConnection
from src.core.vpn_backend import WireGuardError
from src.core.vpn_linux import LinuxWireGuard, LinuxIdentityStore, linux_tunnel_name, read_private, trusted_binary


class SimulatedLinux(LinuxWireGuard):
    def __init__(self, root, public_key):
        self.directory = Path(root)
        self.public_key = public_key
        self.wg, self.ip = 'wg', 'ip'
        self.interfaces = {}
        self.commands = []
        self.routes = []
        self.handshake = 0
        self.fail_step = None

    def _lock(self):
        return nullcontext()

    def _command(self, binary, args, **kwargs):
        self.commands.append((binary, args, kwargs))
        if self.fail_step and args[:len(self.fail_step)] == self.fail_step:
            raise WireGuardError('Simulated command failure')
        if args == ['-json', '-details', 'link', 'show']:
            return 0, json.dumps(list(self.interfaces.values())).encode()
        if args[:4] == ['-json', '-4', 'route', 'show']:
            return 0, json.dumps(self.routes).encode()
        if args[:2] == ['link', 'add']:
            name = args[3]
            self.interfaces[name] = {'ifname': name, 'flags': [], 'linkinfo': {'info_kind': 'wireguard'}}
        elif args[:2] == ['link', 'delete']:
            self.interfaces.pop(args[3], None)
        elif args[:2] == ['link', 'set']:
            name = args[3]
            if args[4] == 'alias':
                self.interfaces[name]['ifalias'] = args[5]
            elif args[4] == 'up':
                self.interfaces[name]['flags'] = ['UP']
        elif binary == self.wg and args[0] == 'show':
            if args[2] == 'public-key':
                return 0, self.public_key.encode()
            return 0, f'{self.public_key}\t{self.handshake}\n'.encode()
        return 0, b''


class TestLinuxVPN(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server, self.client = generate_identity(), generate_identity()
        self.runtime = SimulatedLinux(self.temp.name, self.server.public_key)

    @contextmanager
    def simulated_memory(self):
        captured = io.BytesIO()
        @contextmanager
        def stream(*args, **kwargs):
            yield captured
        fcntl = SimpleNamespace(fcntl=lambda *args: 0, F_ADD_SEALS=1, F_SEAL_WRITE=2,
                                F_SEAL_GROW=4, F_SEAL_SHRINK=8, F_SEAL_SEAL=16)
        with ExitStack() as stack:
            stack.enter_context(patch.dict('sys.modules', {'fcntl': fcntl}))
            stack.enter_context(patch('src.core.vpn_linux.os.memfd_create', return_value=37, create=True))
            stack.enter_context(patch('src.core.vpn_linux.os.MFD_CLOEXEC', 1, create=True))
            stack.enter_context(patch('src.core.vpn_linux.os.MFD_ALLOW_SEALING', 2, create=True))
            stack.enter_context(patch('src.core.vpn_linux.os.dup', return_value=38))
            stack.enter_context(patch('src.core.vpn_linux.os.fdopen', side_effect=stream))
            stack.enter_context(patch('src.core.vpn_linux.os.lseek'))
            stack.enter_context(patch('src.core.vpn_linux.os.close'))
            stack.enter_context(patch('src.core.vpn_linux.publish_private', side_effect=lambda path, data: Path(path).write_bytes(data)))
            stack.enter_context(patch('src.core.vpn_linux.read_private', side_effect=lambda path, maximum=65536: Path(path).read_bytes()))
            yield captured

    def test_names_fit_linux_interface_limit_and_are_stable(self):
        name = linux_tunnel_name('server', self.server.public_key)
        self.assertEqual(len(name), 15)
        self.assertEqual(name, linux_tunnel_name('server', self.server.public_key))
        self.assertNotEqual(name, linux_tunnel_name('client', self.server.public_key))

    def test_server_uses_memfd_no_secret_arguments_and_removes_interface(self):
        with self.simulated_memory() as data:
            status = self.runtime.start_server(self.server, '10.77.0.0/24', 51820, (PeerPlan(self.client.public_key, '10.77.0.2'),))
            self.assertIn(self.server.private_key.encode(), data.getvalue())
            self.assertNotIn(b'Address =', data.getvalue())
            self.assertTrue(status['service_running'])
            self.assertFalse(status['handshake_verified'])
            self.assertNotIn(self.server.private_key, str(self.runtime.commands))
            self.assertEqual([entry[1][:2] for entry in self.runtime.commands if entry[0] == 'wg' and entry[1][0] == 'setconf'], [['setconf', status['name']]])
            self.runtime.stop(status['name'])
        self.assertEqual(self.runtime.interfaces, {})
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_client_adds_only_server_route_and_confirms_recent_handshake(self):
        self.runtime.public_key = self.client.public_key
        self.runtime.handshake = int(time.time())
        profile = ClientConnection('10.77.0.0/24', '10.77.0.2', self.client.public_key, self.server.public_key, 'vpn.example.com', 51820)
        with self.simulated_memory():
            status = self.runtime.start_client(self.client, profile)
        self.assertTrue(status['handshake_verified'])
        self.assertTrue(any(args[:3] == ['route', 'add', '10.77.0.1/32'] for _, args, _ in self.runtime.commands))
        self.assertNotIn('0.0.0.0/0', str(self.runtime.commands))

    def test_failed_configuration_rolls_back_created_interface(self):
        self.runtime.fail_step = ['setconf']
        with self.simulated_memory(), self.assertRaises(WireGuardError):
            self.runtime.start_server(self.server, '10.77.0.0/24', 51820, ())
        self.assertEqual(self.runtime.interfaces, {})
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_failure_in_status_check_also_rolls_back(self):
        self.runtime.fail_step = ['show']
        with self.simulated_memory(), self.assertRaises(WireGuardError):
            self.runtime.start_server(self.server, '10.77.0.0/24', 51820, ())
        self.assertEqual(self.runtime.interfaces, {})

    def test_unknown_interface_is_never_removed(self):
        name = linux_tunnel_name('server', self.server.public_key)
        self.runtime.interfaces[name] = {'ifname': name, 'flags': ['UP']}
        with self.simulated_memory(), self.assertRaises(FileNotFoundError):
            self.runtime.stop(name)
        self.assertIn(name, self.runtime.interfaces)
        self.assertFalse(any(args[:2] == ['link', 'delete'] for _, args, _ in self.runtime.commands))

    def test_overlapping_routes_fail_before_interface_creation(self):
        self.runtime.routes = [{'dst': '10.77.0.0/16', 'dev': 'eth0'}]
        with self.simulated_memory(), self.assertRaises(ValueError):
            self.runtime.start_server(self.server, '10.77.0.0/24', 51820, ())
        self.assertEqual(self.runtime.interfaces, {})

    def test_credential_encryption_uses_stdin_and_host_key(self):
        store = LinuxIdentityStore.__new__(LinuxIdentityStore)
        store.binary = Path('/usr/bin/systemd-creds')
        with patch('src.core.vpn_linux._run', return_value=(0, b'encrypted')) as run:
            self.assertEqual(store._crypt('server', b'private-fixture'), b'encrypted')
        args = run.call_args.args[1]
        self.assertIn('--with-key=host', args)
        self.assertIn('--name=serverpy-vpn-server', args)
        self.assertNotIn('private-fixture', str(args))
        self.assertEqual(run.call_args.kwargs['payload'], b'private-fixture')

    def test_unprotected_private_files_are_rejected_before_reading(self):
        with patch('src.core.vpn_linux.os.O_NOFOLLOW', 0, create=True), patch('src.core.vpn_linux.os.O_NONBLOCK', 0, create=True), patch('src.core.vpn_linux.os.open', return_value=5), patch('src.core.vpn_linux.os.fstat', return_value=SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0)), patch('src.core.vpn_linux.os.close'), patch('src.core.vpn_linux.os.fdopen') as read:
            with self.assertRaises(WireGuardError):
                read_private('fixture')
        read.assert_not_called()

    def test_linux_requires_privileges_before_tool_execution(self):
        with patch('src.core.vpn_linux.sys.platform', 'linux'), patch('src.core.vpn_linux.os.geteuid', return_value=1000, create=True), patch('src.core.vpn_linux._run') as run:
            with self.assertRaises(WireGuardError):
                LinuxWireGuard()
            with self.assertRaises(WireGuardError):
                LinuxIdentityStore()
        run.assert_not_called()

    def test_credential_store_publishes_only_ciphertext_and_never_replaces_identity(self):
        store = LinuxIdentityStore.__new__(LinuxIdentityStore)
        store.directory = Path(self.temp.name)
        plaintext = []
        def crypt(name, data, decrypt=False):
            if decrypt:
                self.assertEqual(data, b'ciphertext-fixture')
                return plaintext[0]
            plaintext.append(data)
            return b'ciphertext-fixture'
        with patch.object(store, '_crypt', side_effect=crypt), patch('src.core.vpn_linux.private_directory'), patch('src.core.vpn_linux.read_private', side_effect=lambda path: Path(path).read_bytes()):
            identity = store.create('client')
            path = store._path('client')
            self.assertEqual(path.read_bytes(), b'ciphertext-fixture')
            self.assertNotIn(identity.private_key.encode(), path.read_bytes())
            self.assertEqual(store.load('client'), identity)
            with self.assertRaises(FileExistsError):
                store.create('client')
            self.assertEqual(store.load('client'), identity)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [path])

    def test_modified_or_foreign_owner_binary_is_rejected(self):
        from unittest.mock import MagicMock
        binary = MagicMock()
        binary.is_file.return_value = True
        binary.resolve.return_value = binary
        binary.parents = ()
        for owner, mode in ((1000, 0o755), (0, 0o775)):
            binary.stat.return_value = SimpleNamespace(st_uid=owner, st_mode=stat.S_IFREG | mode)
            with patch('src.core.vpn_linux.Path', return_value=binary), self.assertRaises(WireGuardError):
                trusted_binary(('/usr/bin/wg',))

    def test_foreign_alias_with_existing_marker_is_not_deleted(self):
        name = linux_tunnel_name('server', self.server.public_key)
        self.runtime._marker(name).write_text(json.dumps({'public_key': self.server.public_key}))
        self.runtime.interfaces[name] = {'ifname': name, 'flags': ['UP'], 'ifalias': 'another-app', 'linkinfo': {'info_kind': 'wireguard'}}
        with self.simulated_memory(), self.assertRaises(WireGuardError):
            self.runtime.stop(name)
        self.assertIn(name, self.runtime.interfaces)


if __name__ == '__main__':
    unittest.main()
