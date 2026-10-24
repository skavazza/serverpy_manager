import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox
from src.core.findport import invoke, can_stop, bridge_path
from src.gui.findport import FindPortPanel
from src.gui.i18n import InterfaceLanguage


def endpoint(**changes):
    return dict(Porta=8080, Proto='TCP', Endereco='127.0.0.1', PID=999999,
                Processo='python', PodeFechar='SIM', Inicio='123456789',
                Exposicao='Local (PC)', Categoria='Dev / Servidor Local',
                Servico='HTTP', Caminho='C:/python.exe', Motivo='Servidor local', **changes)


class TestFindPortCore(unittest.TestCase):
    def test_platform_and_validation_never_launch_invalid_actions(self):
        with patch('sys.platform', 'win32'), patch('src.core.findport.is_windows_10_or_11', return_value=False), patch('src.core.findport.subprocess.run') as run:
            self.assertFalse(invoke()[0])
            run.assert_not_called()
        with patch('sys.platform', 'linux'), patch('src.core.findport.is_windows_10_or_11', return_value=False):
            ok, result = invoke('Snapshot')
            self.assertTrue(ok)
            self.assertIn('ports', result)
            self.assertIsInstance(result['ports'], list)
        with patch('src.core.findport.is_windows_10_or_11', return_value=True), patch('src.core.findport.subprocess.run') as run:
            for action, item in [('bad', None), ('Block', {'Porta': True, 'Proto': 'TCP'}),
                                 ('Block', {'Porta': 80, 'Proto': 'TCP; bad'}), ('Stop', {'Porta': 80, 'Proto': 'TCP', 'PID': 4})]:
                self.assertFalse(invoke(action, item)[0])
            run.assert_not_called()

    def test_linux_has_native_snapshot_support(self):
        with patch('sys.platform', 'linux'), patch('src.core.findport.is_windows_10_or_11', return_value=False):
            ok, result = invoke('Snapshot')
            self.assertTrue(ok)
            self.assertIn('ports', result)
            self.assertIsInstance(result['ports'], list)

    def test_json_errors_timeout_and_structured_arguments(self):
        with patch('src.core.findport.is_windows_10_or_11', return_value=True), patch('src.core.findport.subprocess.run') as run:
            fixture = {'ok': True, 'ports': [], 'rules': [], 'warnings': ['firewall access denied']}
            run.return_value = SimpleNamespace(returncode=0, stdout=json.dumps(fixture), stderr='')
            self.assertEqual(invoke(), (True, fixture))
            run.return_value = SimpleNamespace(returncode=1, stdout='{"ok":false,"error":"denied"}', stderr='')
            self.assertEqual(invoke(), (False, 'denied'))
            run.return_value = SimpleNamespace(returncode=0, stdout='invalid', stderr='parse failed')
            self.assertEqual(invoke(), (False, 'parse failed'))
            run.side_effect = subprocess.TimeoutExpired('powershell.exe', 60)
            self.assertIn('timed out', invoke()[1])
            run.side_effect = None

            def operation(args, **kwargs):
                self.assertIsInstance(args, list)
                self.assertNotIn('-Command', args)
                self.assertEqual(args[args.index('-ExpectedStarted') + 1], '123456789')
                self.assertEqual(args[args.index('-ProtectedProcessId') + 1], str(os.getpid()))
                Path(args[args.index('-ResultPath') + 1]).write_text('{"ok":true}', encoding='utf-8')
                return SimpleNamespace(returncode=0, stdout='', stderr='')

            run.side_effect = operation
            self.assertTrue(invoke('Stop', endpoint())[0])

    def test_missing_identity_and_self_are_protected(self):
        item = endpoint()
        self.assertTrue(can_stop(item))
        for change in ({'Inicio': ''}, {'Inicio': "123';bad"}, {'PID': os.getpid()}, {'PID': 4}, {'PodeFechar': 'NUNCA'}):
            self.assertFalse(can_stop(dict(item, **change)))


class TestFindPortBridgePath(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.module_file = self.root / 'src' / 'core' / 'findport.py'
        self.module_file.parent.mkdir(parents=True)
        self.module_file.touch()

    def add_helper_pair(self, root, relative_path):
        helper_dir = root / relative_path
        helper_dir.mkdir(parents=True, exist_ok=True)
        (helper_dir / 'gui_bridge.ps1').touch()
        (helper_dir / 'find_ports.ps1').touch()

    def test_prefers_vendor_when_both_helper_pairs_exist(self):
        self.add_helper_pair(self.root, Path('vendor') / 'findport')
        self.add_helper_pair(self.root, Path('findport'))

        with patch('src.core.findport.__file__', str(self.module_file)), \
                patch('src.core.findport.sys.frozen', False, create=True):
            self.assertEqual(bridge_path(), self.root / 'vendor' / 'findport' / 'gui_bridge.ps1')

    def test_falls_back_to_nested_findport_checkout(self):
        self.add_helper_pair(self.root, Path('findport'))

        with patch('src.core.findport.__file__', str(self.module_file)), \
                patch('src.core.findport.sys.frozen', False, create=True):
            self.assertEqual(bridge_path(), self.root / 'findport' / 'gui_bridge.ps1')

    def test_missing_or_incomplete_helper_pairs_raise_file_not_found(self):
        with patch('src.core.findport.__file__', str(self.module_file)), \
                patch('src.core.findport.sys.frozen', False, create=True):
            with self.assertRaisesRegex(FileNotFoundError, 'The FindPort scripts were not found.'):
                bridge_path()

            for relative_path in (Path('vendor') / 'findport', Path('findport')):
                helper_dir = self.root / relative_path
                helper_dir.mkdir(parents=True, exist_ok=True)
                (helper_dir / 'gui_bridge.ps1').touch()
                with self.subTest(helper_dir=helper_dir), self.assertRaises(FileNotFoundError):
                    bridge_path()
                (helper_dir / 'gui_bridge.ps1').unlink()

    def test_frozen_meipass_root_finds_vendor_helper(self):
        executable_dir = self.root / 'executable'
        executable_dir.mkdir()
        meipass = self.root / 'bundle'
        self.add_helper_pair(meipass, Path('vendor') / 'findport')

        with patch('src.core.findport.__file__', str(self.module_file)), \
                patch('src.core.findport.sys.frozen', True, create=True), \
                patch('src.core.findport.sys.executable', str(executable_dir / 'serverpy.exe')), \
                patch('src.core.findport.sys._MEIPASS', str(meipass), create=True):
            self.assertEqual(bridge_path(), meipass / 'vendor' / 'findport' / 'gui_bridge.ps1')


class TestFindPortGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        port = QLineEdit('8080')
        self.controller = SimpleNamespace(language=InterfaceLanguage('pt'), windows_share_supported=True,
            server_manager=SimpleNamespace(httpd=None), window=SimpleNamespace(line_port=port))
        self.panel = FindPortPanel(self.controller)
        self.addCleanup(self.panel.close)

    def populate(self):
        item = endpoint()
        self.panel.ports = [item, dict(item, Porta=53, Proto='UDP', PID=4, Processo='System',
                                      PodeFechar='NUNCA', Exposicao='Rede / Aberta', Categoria='Sistema Critico')]
        self.panel.rules = [{'RuleName': 'FindPort_Block_TCP_8080', 'Enabled': 1, 'Descricao': 'managed'},
                            {'RuleName': 'Unrelated_rule', 'Enabled': 1}]
        self.panel.retranslate()

    def select_port(self, port):
        for row in range(self.panel.table.rowCount()):
            if self.panel.table.item(row, 0).data(0) == port:
                self.panel.table.selectRow(row)
                return
        self.fail('Port not found')

    def test_filters_selection_translation_and_protected_processes(self):
        self.populate()
        self.assertEqual(self.panel.table.rowCount(), 2)
        self.select_port(53)
        self.assertFalse(self.panel.stop_button.isEnabled())
        self.panel.hide_protected.setChecked(True)
        self.assertEqual(self.panel.table.rowCount(), 1)
        self.select_port(8080)
        self.assertTrue(self.panel.stop_button.isEnabled())
        self.assertFalse(self.panel.stop_button.icon().isNull())
        self.controller.language.code = 'en'
        self.panel.retranslate()
        self.assertEqual(self.panel.selected(self.panel.table)['Porta'], 8080)
        self.assertEqual(self.panel.block_button.text(), 'Block port')
        self.assertEqual(self.panel.table.horizontalHeaderItem(0).text(), 'Port')
        self.assertEqual(self.panel.rules_table.rowCount(), 1)
        self.panel.protocol.setCurrentIndex(2)
        self.assertEqual(self.panel.table.rowCount(), 0)
        self.panel.hide_protected.setChecked(False)
        self.assertEqual(self.panel.table.rowCount(), 1)
        self.panel.search.setText('no match')
        self.assertEqual(self.panel.table.rowCount(), 0)

    def test_confirmation_cancel_and_exact_managed_rule(self):
        self.populate()
        self.select_port(8080)
        with patch('src.gui.findport.QMessageBox.question', return_value=QMessageBox.No), patch.object(self.panel, 'start') as start:
            self.panel.manage('Stop')
            start.assert_not_called()
        self.panel.rules_table.selectRow(0)
        with patch('src.gui.findport.QMessageBox.question', return_value=QMessageBox.Yes), patch.object(self.panel, 'start') as start:
            self.panel.manage('Unblock')
            start.assert_called_once_with('Unblock', {'Proto': 'TCP', 'Porta': 8080})

    def test_worker_and_failed_snapshot_clear_stale_actions(self):
        self.populate()
        self.select_port(8080)
        with patch('src.gui.findport.QThreadPool.globalInstance') as pool, patch('src.gui.findport.invoke', return_value=(False, 'Access denied')) as operation:
            self.panel.refresh()
            operation.assert_not_called()
            self.assertTrue(self.panel.loading)
            self.assertFalse(self.panel.stop_button.isEnabled())
            task = pool.return_value.start.call_args.args[0]
            task.run()
            self.app.processEvents()
        self.assertFalse(self.panel.loading)
        self.assertEqual(self.panel.table.rowCount(), 0)
        self.assertIn('Access denied', self.panel.status.text())
        self.assertFalse(self.panel.block_button.isEnabled())

    def test_server_port_filter_and_linux_support(self):
        with patch.object(self.panel, 'refresh'):
            self.panel.find_server()
            self.assertEqual(self.panel.search.text(), '8080')
            self.controller.server_manager.httpd = SimpleNamespace(server_address=('127.0.0.1', 43210))
            self.panel.find_server()
            self.assertEqual(self.panel.search.text(), '43210')
        with patch('src.gui.findport.sys.platform', 'linux'):
            self.controller.windows_share_supported = False
            self.panel.retranslate()
            self.assertTrue(self.panel.supported())
            self.assertTrue(self.panel.refresh_button.isEnabled())
            self.assertNotIn('Windows', self.panel.status.text())


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows PowerShell required')
class TestFindPortPowerShell(unittest.TestCase):
    def test_live_tcp_and_udp_snapshot_without_mutations(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            tcp.bind(('127.0.0.1', 0))
            tcp.listen(1)
            udp.bind(('127.0.0.1', 0))
            ports = {'TCP': tcp.getsockname()[1], 'UDP': udp.getsockname()[1]}
            ok, result = invoke()
            self.assertTrue(ok, result)
            own = [item for item in result['ports'] if item['Porta'] == ports.get(item['Proto']) and item['PID'] == os.getpid()]
            self.assertEqual({item['Proto'] for item in own}, {'TCP', 'UDP'})
            self.assertTrue(all(not can_stop(item) for item in own))

    def test_bridge_with_simulated_cmdlets_never_changes_windows(self):
        bridge = str(bridge_path()).replace("'", "''")
        with tempfile.TemporaryDirectory() as scratch:
            log = str(Path(scratch) / 'audit.log').replace("'", "''")
            script = """
$ErrorActionPreference = 'Stop'
. 'BRIDGE_PATH' -ImportOnly
$Script:LogPath = 'AUDIT_PATH'
function Test-IsAdmin { return $true }
$Script:Rules = @()
$Script:Stopped = 0
function Get-NetFirewallRule { $Script:Rules }
function Get-NetFirewallPortFilter { process { [pscustomobject]@{ LocalPort=8080; Protocol='TCP' } } }
function New-NetFirewallRule { param($Name); $Script:Rules += [pscustomobject]@{ Name=$Name; Enabled=1 } }
function Set-NetFirewallRule { process {} }
function Set-NetFirewallPortFilter { process {} }
function Remove-NetFirewallRule { process { $Script:Rules = @($Script:Rules | Where-Object { $_.Name -ne $input.Name }) } }
$Script:Action = 'Block'; $Script:Port = 8080; $Script:Protocol = 'TCP'
$first = Invoke-GuiAction
$second = Invoke-GuiAction
if ($Script:Rules.Count -ne 1) { throw 'Block was not idempotent' }
$Script:Rules += [pscustomobject]@{ Name='Unrelated'; Enabled=1 }
function Remove-NetFirewallRule { process { $nameToRemove = $_.Name; $Script:Rules = @($Script:Rules | Where-Object { $_.Name -ne $nameToRemove }) } }
$Script:Action = 'Unblock'
$removed = Invoke-GuiAction
if ($Script:Rules.Count -ne 1 -or $Script:Rules[0].Name -ne 'Unrelated') { throw 'Unrelated rule was removed' }
$Script:Started = [datetime]'2026-01-01T00:00:00Z'
function Get-Process { [pscustomobject]@{ Id=45678; ProcessName='python'; StartTime=$Script:Started; Path='python.exe' } }
function Get-NetTCPConnection { [pscustomobject]@{ State='Listen'; LocalPort=8080; OwningProcess=45678; LocalAddress='127.0.0.1' } }
function Get-NetUDPEndpoint { [pscustomobject]@{ LocalPort=8080; OwningProcess=45678; LocalAddress='0.0.0.0' } }
function Stop-Process { process { $Script:Stopped++ } }
$Script:Action='Stop'; $Script:ProcessId=45678; $Script:ExpectedStarted='1'
$rejected = $false
try { Invoke-GuiAction } catch { $rejected = $true }
if (-not $rejected -or $Script:Stopped) { throw 'Changed process was not rejected' }
$Script:ExpectedStarted=$Script:Started.ToUniversalTime().Ticks.ToString()
$ended = Invoke-GuiAction
if ($Script:Stopped -ne 1) { throw 'Verified process was not passed to Stop-Process' }
function Get-Process { [pscustomobject]@{ Id=45678; ProcessName='lsass'; StartTime=$Script:Started; Path='lsass.exe' } }
$rejected=$false
try { Invoke-GuiAction } catch { $rejected=$true }
if (-not $rejected -or $Script:Stopped -ne 1) { throw 'Critical process was not protected' }
$Script:Rules=@()
function Get-Process { [pscustomobject]@{ Id=45678; ProcessName='python'; StartTime=$Script:Started; Path='python.exe' } }
function Get-NetTCPConnection {
    [pscustomobject]@{ State='Listen'; LocalPort=8080; OwningProcess=45678; LocalAddress='127.0.0.1' }
    [pscustomobject]@{ State='Listen'; LocalPort=8080; OwningProcess=45679; LocalAddress='::1' }
}
$ports = @(Obter-PortasAbertas -Strict)
if ($ports.Count -ne 3) { throw 'Endpoint identities were collapsed' }
function Get-NetTCPConnection { throw 'Access denied' }
$rejected=$false
try { Obter-PortasAbertas -Strict } catch { $rejected=$true }
if (-not $rejected) { throw 'Query failure became an empty list' }
function Get-NetTCPConnection { @() }
function Get-NetUDPEndpoint { @() }
if (@(Obter-PortasAbertas -Strict).Count -ne 0) { throw 'Empty inventory produced phantom endpoints' }
function Test-IsAdmin { return $false }
function Start-Process {
    param($ArgumentList, $WindowStyle)
    $decoded = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($ArgumentList[-1]))
    if ($WindowStyle -ne 'Hidden' -or -not $decoded.Contains('gui_bridge.ps1')) { throw 'Invalid elevation command' }
    $Script:ElevationChecked = $true
    throw 'UAC canceled'
}
$Script:Action='Block'; $Script:ResultPath='AUDIT_PATH.result'
$rejected=$false
try { Invoke-GuiAction } catch { $rejected=$true }
if (-not $rejected) { throw 'Elevation cancellation was ignored' }
if (-not $Script:ElevationChecked) { throw 'Elevation command was not validated' }
$lines = @(Get-Content -LiteralPath $Script:LogPath)
if ($lines.Count -ne 4) { throw 'Successful operations were not audited' }
Write-Output 'Simulated FindPort actions passed.'
""".replace('BRIDGE_PATH', bridge).replace('AUDIT_PATH', log)
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                    capture_output=True, text=True, timeout=30,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Simulated FindPort actions passed.', result.stdout)


if __name__ == '__main__':
    unittest.main()
