from unittest.mock import patch
import unittest

from src.core.vpn_backend import identity_store, tunnel_backend, vpn_platform, WireGuardError
from src.core.wireguard_windows import WireGuardError as LegacyError


class TestVPNPlatformSelection(unittest.TestCase):
    def test_windows_uses_existing_implementations(self):
        with patch('src.core.vpn_backend.sys.platform', 'win32'), patch('src.core.vpn_identity.WindowsIdentityStore') as store, patch('src.core.wireguard_windows.WindowsWireGuard') as backend:
            self.assertIs(identity_store('directory'), store.return_value)
            self.assertIs(tunnel_backend(), backend.return_value)
            store.assert_called_once_with('directory')
            self.assertEqual(vpn_platform(), 'windows')

    def test_linux_selects_linux_without_windows_fallback(self):
        with patch('src.core.vpn_backend.sys.platform', 'linux'), patch('src.core.vpn_linux.LinuxIdentityStore') as store, patch('src.core.vpn_linux.LinuxWireGuard') as backend, patch('src.core.wireguard_windows.WindowsWireGuard') as windows:
            self.assertIs(identity_store('directory'), store.return_value)
            self.assertIs(tunnel_backend(), backend.return_value)
            windows.assert_not_called()
            self.assertEqual(vpn_platform(), 'linux')

    def test_unsupported_system_fails_closed(self):
        with patch('src.core.vpn_backend.sys.platform', 'darwin'):
            for operation in (vpn_platform, identity_store, tunnel_backend):
                with self.assertRaises(WireGuardError):
                    operation()

    def test_backend_failure_never_switches_platform_or_key_storage(self):
        with patch('src.core.vpn_backend.sys.platform', 'linux'), patch('src.core.vpn_linux.LinuxWireGuard', side_effect=WireGuardError('missing prerequisites')), patch('src.core.wireguard_windows.WindowsWireGuard') as windows:
            with self.assertRaises(WireGuardError):
                tunnel_backend()
            windows.assert_not_called()
        self.assertIs(LegacyError, WireGuardError)
