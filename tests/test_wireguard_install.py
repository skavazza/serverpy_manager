import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.core.vpn_backend import WireGuardError
from src.core import wireguard_install


class _Response:
    def __init__(self, content):
        self.stream = io.BytesIO(content)
        self.headers = {'Content-Length': str(len(content))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.stream.close()

    def read(self, size):
        return self.stream.read(size)


class TestWireGuardInstall(unittest.TestCase):
    def test_download_verifies_hash_and_signature_before_publishing(self):
        content = b'official-installer'
        expected_hash = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'wireguard.msi'
            with (
                patch.object(wireguard_install, '_INSTALLER_SHA256', expected_hash),
                patch.object(wireguard_install.urllib.request, 'urlopen', return_value=_Response(content)) as download,
                patch.object(
                    wireguard_install,
                    '_powershell',
                    return_value={'valid': True, 'publisher': 'WireGuard LLC'},
                ) as verify,
            ):
                wireguard_install._download_installer(destination)
            self.assertEqual(destination.read_bytes(), content)
            self.assertEqual(verify.call_count, 1)
            self.assertIn(str(destination.parent), verify.call_args.args[1]['path'])
            self.assertIn('ConvertTo-Json -Compress', verify.call_args.args[0])
            self.assertEqual(download.call_args.args[0], wireguard_install._INSTALLER_URL)
            self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_hash_mismatch_does_not_publish_installer(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'wireguard.msi'
            with (
                patch.object(wireguard_install, '_INSTALLER_SHA256', '0' * 64),
                patch.object(wireguard_install.urllib.request, 'urlopen', return_value=_Response(b'not trusted')),
            ):
                with self.assertRaisesRegex(WireGuardError, 'SHA-256'):
                    wireguard_install._download_installer(destination)
            self.assertFalse(destination.exists())
            self.assertEqual(list(destination.parent.iterdir()), [])

    def test_launch_uses_uac_msi_install_without_reboot(self):
        with tempfile.TemporaryDirectory() as temporary:
            installer = Path(temporary) / 'wireguard installer.msi'
            shell = SimpleNamespace(ShellExecuteW=Mock(return_value=33))
            kernel32 = SimpleNamespace(
                GetSystemDirectoryW=Mock(
                    side_effect=lambda buffer, _size: (
                        setattr(buffer, 'value', temporary) or len(temporary)
                    )
                )
            )
            with (
                patch.object(
                    wireguard_install.ctypes,
                    'windll',
                    SimpleNamespace(shell32=shell, kernel32=kernel32),
                    create=True,
                ),
            ):
                wireguard_install._launch_installer(installer)
            arguments = shell.ShellExecuteW.call_args.args
            self.assertEqual(arguments[1], 'runas')
            self.assertEqual(arguments[2], str(Path(temporary) / 'msiexec.exe'))
            self.assertIn('/passive', arguments[3])
            self.assertIn('/norestart', arguments[3])
            self.assertIn(str(installer), arguments[3])

    def test_launch_reports_system_directory_lookup_failure(self):
        kernel32 = SimpleNamespace(GetSystemDirectoryW=Mock(return_value=0))
        with patch.object(
            wireguard_install.ctypes,
            'windll',
            SimpleNamespace(kernel32=kernel32),
            create=True,
        ):
            with self.assertRaisesRegex(WireGuardError, 'system directory'):
                wireguard_install._system_directory()


if __name__ == '__main__':
    unittest.main()
