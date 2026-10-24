import hashlib
import io
import os
import stat
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QProcess, QByteArray

from src.core.android import (
    capture_android_screenshot, install_android_apk,
    install_android_platform_tools, list_android_devices,
    list_android_directory, normalize_android_path, send_android_control,
    set_android_reverse, transfer_android_file,
)
from src.core.scrcpy import install_scrcpy, scrcpy_executable
from src.gui.i18n import InterfaceLanguage
from src.gui.storage import AndroidDevicePanel


_HOST_CHMOD = Path.chmod


def assert_executable_permissions(test, path, chmod):
    # A Linux fixture on NTFS cannot expose POSIX executable bits via stat.
    # Always verify the requested chmod and verify the actual bits on POSIX.
    test.assertTrue(any(call.args[0].name == path.name and call.args[1] & 0o111
                        for call in chmod.call_args_list))
    if os.name != 'nt':
        test.assertTrue(path.stat().st_mode & 0o111)


class TestAndroidADB(unittest.TestCase):
    def adb(self, stdout='', returncode=0, stderr=''):
        return patch(
            'src.core.android.shutil.which', return_value='/tools/adb',
        ), patch(
            'src.core.android.subprocess.run',
            return_value=SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr),
        )

    def test_device_listing_includes_unauthorized_status(self):
        output = (
            'List of devices attached\n'
            'device-1 device product:pixel model:Pixel_8 transport_id:1\n'
            'device-2 unauthorized usb:1-2\n'
        )
        which, run = self.adb(output)
        with which, run as execute:
            self.assertEqual(list_android_devices(), [
                {'serial': 'device-1', 'state': 'device', 'model': 'Pixel 8'},
                {'serial': 'device-2', 'state': 'unauthorized', 'model': ''},
            ])
        self.assertEqual(execute.call_args.args[0], ['/tools/adb', 'devices', '-l'])

    def test_directory_listing_quotes_remote_path_and_marks_folders(self):
        which, run = self.adb('Camera/\nreport final.jpg\n.hidden\n')
        with which, run as execute:
            self.assertEqual(list_android_directory('device-1', '/sdcard/My Files'), [
                {'name': 'Camera', 'is_dir': True},
                {'name': 'report final.jpg', 'is_dir': False},
                {'name': '.hidden', 'is_dir': False},
            ])
        self.assertEqual(
            execute.call_args.args[0][-1],
            "ls -1Ap -- '/sdcard/My Files'",
        )

    def test_file_transfers_use_arguments_without_local_shell(self):
        which, run = self.adb()
        with which, run as execute:
            transfer_android_file(
                'device-1', 'pull', '/tmp/photo final.jpg', '/sdcard/DCIM/photo final.jpg',
            )
        self.assertEqual(execute.call_args.args[0], [
            '/tools/adb', '-s', 'device-1', 'pull',
            '/sdcard/DCIM/photo final.jpg', '/tmp/photo final.jpg',
        ])
        self.assertFalse(execute.call_args.kwargs.get('shell', False))

    def test_android_controls_use_allowlisted_adb_arguments(self):
        expected_key_events = {
            'back': '4',
            'home': '3',
            'recent_apps': '187',
            'power': '26',
            'screen_off': '223',
            'screen_on': '224',
            'volume_up': '24',
            'volume_down': '25',
        }
        for action, keycode in expected_key_events.items():
            with patch('src.core.android._run_adb', return_value='') as run:
                send_android_control('device-1', action)
            self.assertEqual(run.call_args.args[0], [
                '-s', 'device-1', 'shell', 'input', 'keyevent', keycode,
            ])
        with patch('src.core.android._run_adb', return_value='') as run:
            send_android_control('device-1', 'quick_settings')
        self.assertEqual(run.call_args.args[0], [
            '-s', 'device-1', 'shell', 'cmd', 'statusbar', 'expand-settings',
        ])
        with self.assertRaises(ValueError):
            send_android_control('device-1', 'execute arbitrary command')

    def test_android_rotation_disables_auto_rotate_and_can_restore_it(self):
        with patch('src.core.android._run_adb', side_effect=['1', '', '']) as run:
            send_android_control('device-1', 'rotate')
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ['-s', 'device-1', 'shell', 'settings', 'get', 'system', 'user_rotation'],
                ['-s', 'device-1', 'shell', 'settings', 'put', 'system', 'accelerometer_rotation', '0'],
                ['-s', 'device-1', 'shell', 'settings', 'put', 'system', 'user_rotation', '2'],
            ],
        )
        with patch('src.core.android._run_adb', return_value='') as run:
            send_android_control('device-1', 'auto_rotation')
        self.assertEqual(run.call_args.args[0], [
            '-s', 'device-1', 'shell', 'settings', 'put',
            'system', 'accelerometer_rotation', '1',
        ])
        with patch('src.core.android._run_adb', return_value='invalid'):
            with self.assertRaisesRegex(OSError, 'rotation setting'):
                send_android_control('device-1', 'rotate')

    def test_apk_install_requires_existing_apk_and_uses_argument_list(self):
        with tempfile.TemporaryDirectory() as folder:
            apk = Path(folder) / 'trusted app.apk'
            apk.write_bytes(b'apk')
            with patch('src.core.android.shutil.which', return_value='/tools/adb'), patch(
                'src.core.android.subprocess.run',
                return_value=SimpleNamespace(stdout='Success', returncode=0, stderr=''),
            ) as run:
                self.assertEqual(
                    install_android_apk('device-1', str(apk)),
                    'Success',
                )
            self.assertEqual(run.call_args.args[0], [
                '/tools/adb', '-s', 'device-1', 'install', str(apk),
            ])
            with self.assertRaisesRegex(ValueError, 'APK'):
                install_android_apk('device-1', str(Path(folder) / 'missing.apk'))

    def test_screenshot_is_validated_and_saved_atomically(self):
        png = b'\x89PNG\r\n\x1a\nimage-data'
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / 'screen.png'
            with patch('src.core.android.shutil.which', return_value='/tools/adb'), patch(
                'src.core.android.subprocess.run',
                return_value=SimpleNamespace(stdout=png, returncode=0, stderr=b''),
            ) as run:
                self.assertEqual(
                    capture_android_screenshot('device-1', str(destination)),
                    str(destination),
                )
            self.assertEqual(destination.read_bytes(), png)
            self.assertEqual(run.call_args.args[0], [
                '/tools/adb', '-s', 'device-1', 'exec-out', 'screencap', '-p',
            ])
            with patch('src.core.android.shutil.which', return_value='/tools/adb'), patch(
                'src.core.android.subprocess.run',
                return_value=SimpleNamespace(stdout=b'not png', returncode=0, stderr=b''),
            ):
                with self.assertRaisesRegex(OSError, 'valid PNG'):
                    capture_android_screenshot('device-1', str(destination), overwrite=True)
            self.assertEqual(destination.read_bytes(), png)

    def test_reverse_mapping_and_invalid_arguments(self):
        which, run = self.adb()
        with which, run as execute:
            set_android_reverse('device-1', 8080, True)
        self.assertEqual(execute.call_args.args[0], [
            '/tools/adb', '-s', 'device-1', 'reverse', 'tcp:8080', 'tcp:8080',
        ])
        with which, run as execute:
            set_android_reverse('device-1', 8080, False)
        self.assertEqual(execute.call_args.args[0], [
            '/tools/adb', '-s', 'device-1', 'reverse', '--remove', 'tcp:8080',
        ])
        for port in (0, 65536, True):
            with self.assertRaises(ValueError):
                set_android_reverse('device-1', port, True)

    def test_paths_and_adb_errors_are_reported(self):
        for path in ('relative', '', '/bad\npath'):
            with self.assertRaises(ValueError):
                normalize_android_path(path)
        with patch('src.core.android.shutil.which', return_value=None), patch(
            'src.core.android._managed_adb_executable', return_value=None,
        ):
            with self.assertRaisesRegex(FileNotFoundError, 'adb'):
                list_android_devices()
        with patch('src.core.android.shutil.which', return_value='/tools/adb'), patch(
            'src.core.android.subprocess.run',
            side_effect=subprocess.TimeoutExpired('adb', 1),
        ):
            with self.assertRaisesRegex(TimeoutError, 'timed out'):
                list_android_devices()
        with patch('src.core.android.shutil.which', return_value='/tools/adb'), patch(
            'src.core.android.subprocess.run',
            return_value=SimpleNamespace(stdout='', returncode=1, stderr='device unauthorized'),
        ):
            with self.assertRaisesRegex(OSError, 'unauthorized'):
                list_android_devices()

    @patch.object(Path, 'chmod', autospec=True, side_effect=_HOST_CHMOD)
    def test_platform_tools_download_is_verified_and_installed_for_user(self, chmod):
        archive_data = io.BytesIO()
        with zipfile.ZipFile(archive_data, 'w') as archive:
            archive.writestr('platform-tools/adb', b'adb-binary')
        payload = archive_data.getvalue()
        config = {
            'url': 'https://example.invalid/platform-tools.zip',
            'sha256': hashlib.sha256(payload).hexdigest(),
            'members': ('platform-tools/adb',),
            'executable': 'adb',
        }

        class Response:
            headers = {'Content-Length': str(len(payload))}

            def __init__(self):
                self.data = io.BytesIO(payload)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, size):
                return self.data.read(size)

        with patch('src.core.android.sys.platform', 'linux'), tempfile.TemporaryDirectory() as folder, patch(
            'src.core.android._platform_tools_config', return_value=config,
        ), patch(
            'src.core.android._platform_tools_directory',
            return_value=Path(folder) / 'platform-tools',
        ), patch(
            'src.core.android.urllib.request.urlopen', return_value=Response(),
        ):
            progress = []
            installed = Path(install_android_platform_tools(
                lambda current, total: progress.append((current, total)),
            ))
            self.assertEqual(installed.read_bytes(), b'adb-binary')
            assert_executable_permissions(self, installed, chmod)
            self.assertEqual(progress[-1], (len(archive_data.getvalue()), len(archive_data.getvalue())))
            self.assertEqual(installed.parent.name, 'platform-tools')

    def test_platform_tools_checksum_mismatch_does_not_install(self):
        config = {
            'url': 'https://example.invalid/platform-tools.zip',
            'sha256': '0' * 64,
            'members': ('platform-tools/adb',),
            'executable': 'adb',
        }

        class Response:
            headers = {}

            def __init__(self):
                self.data = io.BytesIO(b'unverified archive')

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, size):
                return self.data.read(size)

        with tempfile.TemporaryDirectory() as folder, patch(
            'src.core.android._platform_tools_config', return_value=config,
        ), patch(
            'src.core.android._platform_tools_directory',
            return_value=Path(folder) / 'platform-tools',
        ), patch(
            'src.core.android.urllib.request.urlopen', return_value=Response(),
        ):
            with self.assertRaisesRegex(OSError, 'SHA-256 verification failed'):
                install_android_platform_tools()
            self.assertFalse((Path(folder) / 'platform-tools').exists())


class TestScrcpyInstaller(unittest.TestCase):
    def make_release(self, members):
        archive_data = io.BytesIO()
        with zipfile.ZipFile(archive_data, 'w') as archive:
            for name, content in members.items():
                archive.writestr(name, content)
        payload = archive_data.getvalue()
        filename = 'scrcpy-win64-v5.0.1.zip'
        return payload, {
            'filename': filename,
            'sha256': hashlib.sha256(payload).hexdigest(),
            'archive': 'zip',
            'executable': 'scrcpy.exe',
        }

    def response(self, payload):
        class Response:
            headers = {'Content-Length': str(len(payload))}

            def __init__(self):
                self.data = io.BytesIO(payload)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, size):
                return self.data.read(size)

        return Response()

    def test_official_scrcpy_archive_is_hash_verified_and_installed(self):
        root = 'scrcpy-win64-v5.0.1'
        archive_data = io.BytesIO()
        with zipfile.ZipFile(archive_data, 'w') as archive:
            for name, content in (
                (f'{root}/scrcpy.exe', b'scrcpy-binary'),
                (f'{root}/scrcpy-server', b'server-binary'),
                (f'{root}/SDL2.dll', b'support-library'),
            ):
                info = zipfile.ZipInfo(name)
                info.external_attr = (stat.S_IFREG | 0o755) << 16
                archive.writestr(info, content)
        payload = archive_data.getvalue()
        config = {
            'filename': f'{root}.zip',
            'sha256': hashlib.sha256(payload).hexdigest(),
            'archive': 'zip',
            'executable': 'scrcpy.exe',
        }
        with tempfile.TemporaryDirectory() as folder, patch(
            'src.core.scrcpy._release_config', return_value=config,
        ), patch(
            'src.core.scrcpy._scrcpy_directory',
            return_value=Path(folder) / 'scrcpy-5.0.1',
        ), patch(
            'src.core.scrcpy.urllib.request.urlopen',
            return_value=self.response(payload),
        ):
            progress = []
            executable = Path(install_scrcpy(
                lambda downloaded, total: progress.append((downloaded, total)),
            ))
            self.assertEqual(executable.read_bytes(), b'scrcpy-binary')
            self.assertEqual((executable.parent / 'scrcpy-server').read_bytes(), b'server-binary')
            self.assertEqual((executable.parent / 'SDL2.dll').read_bytes(), b'support-library')
            self.assertTrue(executable.stat().st_mode & 0o111)
            self.assertEqual(
                progress[-1],
                (len(payload), len(payload)),
            )

    def test_checksum_mismatch_does_not_extract_scrcpy(self):
        payload, config = self.make_release({})
        config['sha256'] = '0' * 64
        with tempfile.TemporaryDirectory() as folder, patch(
            'src.core.scrcpy._release_config', return_value=config,
        ), patch(
            'src.core.scrcpy._scrcpy_directory',
            return_value=Path(folder) / 'scrcpy-5.0.1',
        ), patch(
            'src.core.scrcpy.urllib.request.urlopen',
            return_value=self.response(payload),
        ):
            with self.assertRaisesRegex(OSError, 'SHA-256 verification failed'):
                install_scrcpy()
            self.assertFalse((Path(folder) / 'scrcpy-5.0.1').exists())

    def test_unsafe_archive_path_is_rejected(self):
        root = 'scrcpy-win64-v5.0.1'
        payload, config = self.make_release({
            f'{root}/scrcpy.exe': b'scrcpy-binary',
            f'{root}/scrcpy-server': b'server-binary',
            f'{root}/../outside.txt': b'unsafe',
        })
        with tempfile.TemporaryDirectory() as folder, patch(
            'src.core.scrcpy._release_config', return_value=config,
        ), patch(
            'src.core.scrcpy._scrcpy_directory',
            return_value=Path(folder) / 'scrcpy-5.0.1',
        ), patch(
            'src.core.scrcpy.urllib.request.urlopen',
            return_value=self.response(payload),
        ):
            with self.assertRaisesRegex(OSError, 'Unsafe path'):
                install_scrcpy()
            self.assertFalse((Path(folder) / 'outside.txt').exists())

    @patch.object(Path, 'chmod', autospec=True, side_effect=_HOST_CHMOD)
    def test_official_linux_tarball_is_installed(self, chmod):
        root = 'scrcpy-linux-x86_64-v5.0.1'
        archive_data = io.BytesIO()
        with tarfile.open(fileobj=archive_data, mode='w:gz') as archive:
            for name, content in (
                (f'{root}/scrcpy', b'scrcpy-binary'),
                (f'{root}/scrcpy-server', b'server-binary'),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = 0o755
                archive.addfile(info, io.BytesIO(content))
        payload = archive_data.getvalue()
        config = {
            'filename': f'{root}.tar.gz',
            'sha256': hashlib.sha256(payload).hexdigest(),
            'archive': 'tar.gz',
            'executable': 'scrcpy',
        }
        with tempfile.TemporaryDirectory() as folder, patch(
            'src.core.scrcpy._release_config', return_value=config,
        ), patch(
            'src.core.scrcpy._scrcpy_directory',
            return_value=Path(folder) / 'scrcpy-5.0.1',
        ), patch(
            'src.core.scrcpy.urllib.request.urlopen',
            return_value=self.response(payload),
        ), patch('src.core.scrcpy.sys.platform', 'linux'):
            executable = Path(install_scrcpy())
            self.assertEqual(executable.read_bytes(), b'scrcpy-binary')
            assert_executable_permissions(self, executable, chmod)
            self.assertEqual(
                (executable.parent / 'scrcpy-server').read_bytes(),
                b'server-binary',
            )

    @patch.object(Path, 'chmod', autospec=True, side_effect=_HOST_CHMOD)
    def test_existing_install_repairs_scrcpy_and_bundled_adb_permissions(self, chmod):
        with tempfile.TemporaryDirectory() as folder:
            install = Path(folder)
            config = {'executable': 'scrcpy'}
            executable = install / 'scrcpy'
            bundled_adb = install / 'adb'
            executable.write_bytes(b'scrcpy')
            bundled_adb.write_bytes(b'adb')
            executable.chmod(0o600)
            bundled_adb.chmod(0o600)
            with patch('src.core.scrcpy.sys.platform', 'linux'), patch(
                'src.core.scrcpy.platform.machine', return_value='x86_64',
            ), patch('src.core.scrcpy.shutil.which', return_value=None), patch(
                'src.core.scrcpy._release_config', return_value=config,
            ), patch(
                'src.core.scrcpy._scrcpy_directory', return_value=install,
            ):
                self.assertEqual(scrcpy_executable(), str(executable))
            assert_executable_permissions(self, executable, chmod)
            assert_executable_permissions(self, bundled_adb, chmod)

    def test_supported_platforms_are_limited_to_official_builds(self):
        with patch('src.core.scrcpy.sys.platform', 'win32'), patch(
            'src.core.scrcpy.platform.machine', return_value='ARM64',
        ):
            from src.core.scrcpy import scrcpy_download_supported
            self.assertTrue(scrcpy_download_supported())
        with patch('src.core.scrcpy.sys.platform', 'linux'), patch(
            'src.core.scrcpy.platform.machine', return_value='x86_64',
        ):
            self.assertTrue(scrcpy_download_supported())
        with patch('src.core.scrcpy.sys.platform', 'linux'), patch(
            'src.core.scrcpy.platform.machine', return_value='aarch64',
        ):
            self.assertFalse(scrcpy_download_supported())


class TestAndroidDevicePanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = SimpleNamespace(
            language=InterfaceLanguage('pt'),
            server_manager=SimpleNamespace(is_running=False),
            window=SimpleNamespace(line_port=SimpleNamespace(text=lambda: '8080')),
        )
        self.panel = AndroidDevicePanel(self.controller)
        self.addCleanup(self.panel.close)

    def test_refresh_handles_authorized_and_unauthorized_devices(self):
        self.panel.task_finished(True, (
            'devices', True, [
                {'serial': 'waiting', 'state': 'unauthorized', 'model': ''},
            ],
        ))
        self.assertEqual(self.panel.device.count(), 1)
        self.assertIn('Nenhum dispositivo Android autorizado', self.panel.status.text())
        self.assertFalse(self.panel.pull_button.isEnabled())

        with patch('src.gui.storage.QThreadPool.globalInstance') as pool:
            pool.return_value.start.side_effect = lambda task: None
            self.panel.task_finished(True, (
                'devices', True, [
                    {'serial': 'authorized', 'state': 'device', 'model': 'Pixel'},
                ],
            ))
            pool.return_value.start.assert_called_once()
        self.assertEqual(self.panel.device.currentData()['serial'], 'authorized')
        self.assertTrue(self.panel.status.text().startswith('Operando'))
        self.panel.device.setCurrentIndex(-1)
        self.assertIsNone(self.panel.selected_device())
        self.assertFalse(self.panel.push_button.isEnabled())

    def test_usb_reverse_uses_running_server_port_and_tls_scheme(self):
        server = SimpleNamespace(
            is_running=True,
            httpd=SimpleNamespace(
                server_address=('127.0.0.1', 8443),
                app_config={'use_tls': True},
            ),
        )
        self.controller.server_manager = server
        self.panel.device.blockSignals(True)
        self.panel.device.addItem(
            'Pixel', {'serial': 'device-1', 'state': 'device', 'model': 'Pixel'},
        )
        self.panel.device.blockSignals(False)
        tasks = []
        with patch('src.gui.storage.QThreadPool.globalInstance') as pool, patch(
            'src.gui.storage.set_android_reverse', return_value='',
        ) as reverse:
            pool.return_value.start.side_effect = tasks.append
            self.panel.set_reverse(True)
            self.assertEqual(self.panel.reverse_url, 'https://127.0.0.1:8443')
            self.assertEqual(tasks[0].operation(), (True, ''))
            reverse.assert_called_once_with('device-1', 8443, True)
            self.panel.task_finished(True, ('reverse', True, (True, '')))
        self.assertIn('https://127.0.0.1:8443', self.panel.status.text())

        server.is_running = False
        with patch('src.gui.storage.QThreadPool.globalInstance') as pool, patch(
            'src.gui.storage.set_android_reverse', return_value='',
        ) as reverse:
            pool.return_value.start.side_effect = tasks.append
            self.panel.set_reverse(False)
            self.assertEqual(tasks[-1].operation(), (False, ''))
            reverse.assert_called_once_with('device-1', 8443, False)

    def test_scrcpy_install_button_state_and_completion(self):
        with patch('src.gui.storage.scrcpy_download_supported', return_value=True), patch(
            'src.gui.storage.scrcpy_available', return_value=False,
        ):
            self.panel.update_actions()
            self.assertTrue(self.panel.install_scrcpy_button.isEnabled())

        with patch('src.gui.storage.scrcpy_download_supported', return_value=True), patch(
            'src.gui.storage.scrcpy_available', return_value=True,
        ):
            self.panel.update_actions()
            self.assertFalse(self.panel.install_scrcpy_button.isEnabled())

        self.panel.install_progress.setVisible(True)
        self.panel.task_finished(True, (
            'install_scrcpy', True, '/app-data/scrcpy-5.0.1/scrcpy',
        ))
        self.assertFalse(self.panel.install_progress.isVisible())
        self.assertIn('scrcpy oficial instalado', self.panel.status.text())

    def test_scrcpy_session_starts_for_selected_authorized_device(self):
        self.panel.device.blockSignals(True)
        self.panel.device.addItem(
            'Pixel', {'serial': 'usb-123', 'state': 'device', 'model': 'Pixel 8'},
        )
        self.panel.device.blockSignals(False)
        with patch('src.gui.storage.scrcpy_executable', return_value='/tools/scrcpy') as executable, patch(
            'src.gui.storage.scrcpy_available', return_value=True,
        ), patch.object(self.panel.scrcpy_process, 'start') as start:
            self.panel.start_scrcpy()
        executable.assert_called_once()
        self.assertEqual(self.panel.scrcpy_process.program(), '/tools/scrcpy')
        self.assertEqual(self.panel.scrcpy_process.arguments(), [
            '--serial', 'usb-123', '--window-title', 'ServerPy - Pixel 8',
            '--no-clipboard-autosync',
        ])
        start.assert_called_once()

    def test_scrcpy_session_applies_video_and_window_settings(self):
        self.panel.device.blockSignals(True)
        self.panel.device.addItem(
            'Pixel', {'serial': 'usb-123', 'state': 'device', 'model': 'Pixel 8'},
        )
        self.panel.device.blockSignals(False)
        self.panel.resolution.setCurrentIndex(self.panel.resolution.findData(1280))
        self.panel.video_codec.setCurrentIndex(self.panel.video_codec.findData('h265'))
        self.panel.max_fps.setCurrentIndex(self.panel.max_fps.findData(60))
        self.panel.video_bitrate.setValue(12)
        self.panel.forward_audio.setChecked(False)
        for checkbox in (
            self.panel.stay_awake,
            self.panel.turn_screen_off,
            self.panel.always_on_top,
            self.panel.fullscreen,
            self.panel.borderless,
        ):
            checkbox.setChecked(True)

        with patch('src.gui.storage.scrcpy_executable', return_value='/tools/scrcpy'), patch(
            'src.gui.storage.scrcpy_available', return_value=True,
        ), patch.object(self.panel.scrcpy_process, 'start'):
            self.panel.start_scrcpy()

        self.assertEqual(
            self.panel.scrcpy_process.arguments(),
            [
                '--serial', 'usb-123',
                '--window-title', 'ServerPy - Pixel 8',
                '--max-size', '1280',
                '--video-codec', 'h265',
                '--max-fps', '60',
                '--video-bit-rate', '12M',
                '--no-clipboard-autosync',
                '--no-audio',
                '--stay-awake',
                '--turn-screen-off',
                '--always-on-top',
                '--fullscreen',
                '--window-borderless',
            ],
        )

    def test_scrcpy_settings_are_grouped_and_translated(self):
        self.assertEqual(self.panel.video_settings_group.title(), 'Configurações de vídeo')
        self.assertEqual(self.panel.session_settings_group.title(), 'Comportamento da sessão')
        self.assertEqual(self.panel.audio_settings_group.title(), 'Configurações de áudio')
        self.assertEqual(self.panel.resolution.itemText(0), 'Original')
        self.assertEqual(self.panel.max_fps.itemText(0), 'Automático')
        self.assertEqual(self.panel.audio_source.currentText(), 'Saída do aparelho')
        self.assertEqual(self.panel.display_orientation.itemText(0), 'Padrão do aparelho')

    def test_scrcpy_session_applies_audio_and_display_orientation(self):
        self.panel.device.blockSignals(True)
        self.panel.device.addItem(
            'Pixel', {'serial': 'usb-123', 'state': 'device', 'model': 'Pixel 8'},
        )
        self.panel.device.blockSignals(False)
        self.panel.audio_source.setCurrentIndex(
            self.panel.audio_source.findData('playback'),
        )
        self.panel.audio_codec.setCurrentIndex(self.panel.audio_codec.findData('aac'))
        self.panel.audio_bitrate.setCurrentIndex(
            self.panel.audio_bitrate.findData('256K'),
        )
        self.panel.display_orientation.setCurrentIndex(
            self.panel.display_orientation.findData('90'),
        )

        with patch('src.gui.storage.scrcpy_executable', return_value='/tools/scrcpy'), patch(
            'src.gui.storage.scrcpy_available', return_value=True,
        ), patch.object(self.panel.scrcpy_process, 'start'):
            self.panel.start_scrcpy()

        arguments = self.panel.scrcpy_process.arguments()
        self.assertIn('--display-orientation', arguments)
        self.assertEqual(arguments[arguments.index('--display-orientation') + 1], '90')
        self.assertIn('--audio-source', arguments)
        self.assertEqual(arguments[arguments.index('--audio-source') + 1], 'playback')
        self.assertIn('--audio-codec', arguments)
        self.assertEqual(arguments[arguments.index('--audio-codec') + 1], 'aac')
        self.assertIn('--audio-bit-rate', arguments)
        self.assertEqual(arguments[arguments.index('--audio-bit-rate') + 1], '256K')

    def test_audio_settings_are_disabled_without_audio_forwarding(self):
        self.panel.forward_audio.setChecked(False)
        self.assertFalse(self.panel.audio_source.isEnabled())
        self.assertFalse(self.panel.audio_codec.isEnabled())
        self.assertFalse(self.panel.audio_bitrate.isEnabled())

    def test_scrcpy_session_does_not_start_without_selected_authorized_device(self):
        with patch('src.gui.storage.scrcpy_executable') as executable, patch.object(
            self.panel.scrcpy_process, 'start',
        ) as start:
            self.panel.start_scrcpy()
        executable.assert_not_called()
        start.assert_not_called()

    def test_scrcpy_session_reports_process_failure_and_user_stop(self):
        self.panel.scrcpy_output = 'USB device disconnected'
        with patch.object(self.panel.scrcpy_process, 'readAllStandardOutput', return_value=QByteArray()):
            self.panel.scrcpy_finished(1, QProcess.ExitStatus.CrashExit)
        self.assertIn('encerrado com erro', self.panel.status.text())
        self.assertIn('USB device disconnected', self.panel.status.text())

        self.panel.scrcpy_stopping = True
        with patch.object(self.panel.scrcpy_process, 'readAllStandardOutput', return_value=QByteArray()):
            self.panel.scrcpy_finished(0, QProcess.ExitStatus.NormalExit)
        self.assertIn('Controle de tela scrcpy encerrado', self.panel.status.text())

    def test_scrcpy_is_terminated_when_application_exits(self):
        process = self.panel.scrcpy_process
        with patch.object(
            process, 'state', return_value=QProcess.ProcessState.Running,
        ), patch.object(process, 'terminate') as terminate, patch.object(
            process, 'waitForFinished', side_effect=[False, True],
        ) as wait, patch.object(process, 'kill') as kill:
            self.panel.shutdown_scrcpy()
        terminate.assert_called_once()
        self.assertEqual(wait.call_args_list[0].args, (2000,))
        self.assertEqual(wait.call_args_list[1].args, (1000,))
        kill.assert_called_once()

    def test_adb_install_button_state_and_completion(self):
        with patch('src.gui.storage.android_adb_install_supported', return_value=True), patch(
            'src.gui.storage.android_adb_available', return_value=False,
        ):
            self.panel.update_actions()
            self.assertTrue(self.panel.install_adb_button.isEnabled())

        with patch('src.gui.storage.android_adb_install_supported', return_value=True), patch(
            'src.gui.storage.android_adb_available', return_value=True,
        ):
            self.panel.update_actions()
            self.assertFalse(self.panel.install_adb_button.isEnabled())

        self.panel.install_progress.setVisible(True)
        self.panel.task_finished(True, ('install_adb', True, '/app-data/platform-tools/adb'))
        self.assertFalse(self.panel.install_progress.isVisible())
        self.assertIn('Android Platform-Tools instalado', self.panel.status.text())
