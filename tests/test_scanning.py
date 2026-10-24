import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLineEdit
from src.core import scanning
from src.core.server import ServerManager
from src.gui.scanning import ScannerPanel
from src.gui.i18n import InterfaceLanguage


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
DEVICE = {'id': "scanner ' $(throw 'injected')", 'name': 'Recepção <WIA>'}


def request_data(script):
    encoded = re.search(r"FromBase64String\('([^']+)'\)", script).group(1)
    return json.loads(base64.b64decode(encoded))


class TestScanning(unittest.TestCase):
    def test_discovery_validation_errors_platform_and_timeout(self):
        for raw, expected in [('[]', []), (json.dumps([DEVICE]), [DEVICE]), ('', [])]:
            with patch.object(scanning, '_run', return_value=(True, raw)):
                self.assertEqual(scanning.list_scanners(), (True, expected))
        for raw in ['null', '{}', '[{"name":"Missing ID"}]', 'not json']:
            with patch.object(scanning, '_run', return_value=(True, raw)):
                self.assertFalse(scanning.list_scanners()[0])
        with patch('sys.platform', 'win32'), patch.object(scanning, 'is_windows_10_or_11', return_value=False), patch.object(scanning.subprocess, 'run') as run:
            self.assertFalse(scanning.list_scanners()[0])
            self.assertFalse(scanning.scan_page(DEVICE['id'], '.')[0])
            run.assert_not_called()
        with patch('sys.platform', 'linux'), patch.object(scanning, 'is_windows_10_or_11', return_value=False):
            with patch('shutil.which', return_value='/usr/bin/scanimage'), patch.object(
                scanning.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout="device `test:dev0' is a Test Flatbed Scanner\n", stderr='')
            ):
                ok, devs = scanning.list_scanners()
                self.assertTrue(ok)
                self.assertEqual(len(devs), 1)
                self.assertEqual(devs[0]['id'], 'test:dev0')
        with patch.object(scanning, 'is_windows_10_or_11', return_value=True):
            with patch.object(scanning.subprocess, 'run', side_effect=subprocess.TimeoutExpired('powershell', 20)):
                self.assertIn('timed out', scanning.list_scanners()[1])
            with patch.object(scanning.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='WIA unavailable')):
                self.assertEqual(scanning.list_scanners(), (False, 'WIA unavailable'))

    def test_atomic_publication_unique_names_and_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as scratch, patch.object(scanning, 'is_windows_10_or_11', return_value=True):
            root = Path(scratch)
            temporary = []

            def acquire(script, timeout):
                request = request_data(script)
                self.assertEqual(request['id'], DEVICE['id'])
                self.assertEqual(timeout, 120)
                self.assertEqual(list(root.glob('*.png')), [])
                output = Path(request['output'])
                temporary.append(output.parent)
                output.write_bytes(PNG)
                return True, ''

            with patch.object(scanning, '_run', side_effect=acquire):
                ok, output = scanning.scan_page(DEVICE['id'], root)
            self.assertTrue(ok, output)
            self.assertEqual(Path(output).read_bytes(), PNG)
            self.assertFalse(QImage(output).isNull())
            self.assertFalse(temporary[0].exists())
            with patch.object(scanning, '_run', return_value=(False, 'Device disconnected')):
                self.assertEqual(scanning.scan_page(DEVICE['id'], root), (False, 'Device disconnected'))
            self.assertEqual(len(list(root.glob('*.png'))), 1)
            self.assertEqual(list((root / '.serverpy' / 'uploads').iterdir()), [])

            def invalid(script, timeout):
                Path(request_data(script)['output']).write_bytes(b'incomplete')
                return True, ''

            with patch.object(scanning, '_run', side_effect=invalid):
                self.assertFalse(scanning.scan_page(DEVICE['id'], root)[0])
            self.assertEqual(len(list(root.glob('*.png'))), 1)
            with patch.object(scanning, '_run', side_effect=lambda script, timeout: (Path(request_data(script)['output']).write_bytes(PNG) and True, '')):
                ok, second = scanning.scan_page(DEVICE['id'], root)
            self.assertTrue(ok, second)
            self.assertNotEqual(second, output)
            self.assertEqual(Path(output).read_bytes(), PNG)

    def test_invalid_destination_never_activates_device(self):
        with patch.object(scanning, 'is_windows_10_or_11', return_value=True), patch.object(scanning, '_run') as run:
            for device, folder in [('', '.'), (DEVICE['id'], ''), (DEVICE['id'], 'missing-scanner-output-folder'), (DEVICE['id'], __file__)]:
                self.assertFalse(scanning.scan_page(device, folder)[0])
            run.assert_not_called()

    def test_saved_scan_obeys_existing_http_authentication(self):
        with tempfile.TemporaryDirectory() as root, patch.object(scanning, 'is_windows_10_or_11', return_value=True):
            server = ServerManager()
            ok, message = server.start_server('127.0.0.1', 0, root, auth_credentials=('reader', 'secret'))
            self.assertTrue(ok, message)
            try:
                def acquire(script, timeout):
                    Path(request_data(script)['output']).write_bytes(PNG)
                    return True, ''
                with patch.object(scanning, '_run', side_effect=acquire):
                    ok, output = scanning.scan_page(DEVICE['id'], root)
                self.assertTrue(ok, output)
                url = 'http://127.0.0.1:' + str(server.httpd.server_address[1]) + '/' + Path(output).name
                with self.assertRaises(urllib.error.HTTPError) as failure:
                    urllib.request.urlopen(url, timeout=3)
                self.assertEqual(failure.exception.code, 401)
                failure.exception.close()
                request = urllib.request.Request(url, headers={'Authorization': 'Basic ' + base64.b64encode(b'reader:secret').decode()})
                with urllib.request.urlopen(request, timeout=3) as response:
                    self.assertEqual(response.read(), PNG)
            finally:
                server.stop_server()

    @unittest.skipUnless(os.name == 'nt', 'PowerShell WIA script behavior')
    def test_acquisition_script_with_fake_com_objects_and_disconnection(self):
        # All COM creation is intercepted: no real scanner can be activated.
        fixture = """
$script:fakeImage=[pscustomobject]@{FormatID='PNG_FORMAT'};
$script:fakeImage | Add-Member ScriptMethod SaveFile {param($path) [IO.File]::WriteAllBytes($path,[Convert]::FromBase64String('IMAGE'))};
$item=[pscustomobject]@{};
$item | Add-Member ScriptMethod Transfer {param($format) if ($format -ne 'PNG_FORMAT') {throw 'Unexpected format'}; return $script:fakeImage};
$script:fakeItem=$item;
$items=[pscustomobject]@{Count=1};
$items | Add-Member ScriptMethod Item {param($index) if ($index -ne 1) {throw 'Unexpected item'}; return $script:fakeItem};
$script:fakeDevice=[pscustomobject]@{Items=$items};
$info=[pscustomobject]@{Type=1; DeviceID='DEVICE'};
$info | Add-Member ScriptMethod Connect {return $script:fakeDevice};
$script:fakeManager=[pscustomobject]@{DeviceInfos=@($info)};
function New-Object {param($ComObject) if ($ComObject -ne 'WIA.DeviceManager') {throw 'Unexpected COM object'}; return $script:fakeManager};
""".replace('PNG_FORMAT', scanning.PNG_FORMAT).replace('IMAGE', base64.b64encode(PNG).decode()).replace('DEVICE', DEVICE['id'].replace("'", "''"))
        original = scanning._run
        with tempfile.TemporaryDirectory() as root, patch.object(scanning, 'is_windows_10_or_11', return_value=True):
            with patch.object(scanning, '_run', side_effect=lambda script, timeout: original(fixture + script, timeout)):
                ok, output = scanning.scan_page(DEVICE['id'], root)
                self.assertTrue(ok, output)
                self.assertEqual(Path(output).read_bytes(), PNG)
                ok, error = scanning.scan_page('disconnected', root)
                self.assertFalse(ok)
                self.assertIn('Scanner disconnected', error)
            self.assertEqual(len(list(Path(root).glob('*.png'))), 1)


class TestScannerPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.controller = SimpleNamespace(language=InterfaceLanguage('pt'), windows_share_supported=True,
            server_manager=SimpleNamespace(is_running=False, httpd=None),
            window=SimpleNamespace(line_root_folder=QLineEdit(self.scratch.name)))
        self.panel = ScannerPanel(self.controller)
        self.addCleanup(self.panel.close)

    def wait_idle(self):
        deadline = time.monotonic() + 5
        while self.panel.running and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(self.panel.running)

    def test_async_discovery_scan_and_translation(self):
        gate = threading.Event()
        with patch.object(scanning, 'list_scanners', side_effect=lambda: (gate.wait(3) and True, [DEVICE])):
            self.panel.refresh()
            self.assertFalse(self.panel.refresh_button.isEnabled())
            self.assertFalse(self.panel.scan_button.isEnabled())
            gate.set()
            self.wait_idle()
        self.assertEqual(self.panel.devices.currentData(), DEVICE['id'])
        self.panel.use_server_folder()
        self.assertTrue(self.panel.scan_button.isEnabled())
        output = str(Path(self.scratch.name) / 'scan.png')
        with patch.object(scanning, 'scan_page', return_value=(True, output)) as scan:
            self.panel.scan()
            self.wait_idle()
            scan.assert_called_once_with(DEVICE['id'], self.scratch.name)
        self.assertTrue(self.panel.open_button.isEnabled())
        self.assertIn('Digitalização salva', self.panel.status.text())
        self.controller.language.code = 'en'
        self.panel.retranslate()
        self.assertEqual(self.panel.scan_button.text(), 'Scan one page')
        self.assertEqual(self.panel.devices.currentData(), DEVICE['id'])
        self.assertEqual(self.panel.output.text(), self.scratch.name)

    def test_query_failure_empty_and_unsupported(self):
        self.panel.discovered(True, [DEVICE])
        self.panel.discovered(False, '<WIA unavailable>')
        self.assertEqual(self.panel.devices.count(), 0)
        self.assertIn('<WIA unavailable>', self.panel.status.text())
        self.assertFalse(self.panel.scan_button.isEnabled())
        self.panel.discovered(True, [])
        self.assertIn('Nenhum scanner', self.panel.status.text())
        self.controller.windows_share_supported = False
        self.panel.retranslate()
        with patch.object(scanning, 'list_scanners') as discover:
            self.panel.refresh()
            discover.assert_not_called()
        self.assertFalse(self.panel.refresh_button.isEnabled())
        self.assertIn('driver WIA', self.panel.status.text())

    def test_server_folder_uses_running_root(self):
        self.controller.server_manager.is_running = True
        self.controller.server_manager.httpd = SimpleNamespace(directory=self.scratch.name)
        self.controller.window.line_root_folder.setText('changed preference')
        self.panel.use_server_folder()
        self.assertEqual(self.panel.output.text(), self.scratch.name)
