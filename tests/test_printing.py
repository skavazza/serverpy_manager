import base64
import json
import os
import subprocess
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QMessageBox
from src.core import printing
from src.gui.printing import PrintQueuePanel
from src.gui.i18n import InterfaceLanguage


JOB = dict(ID=3, PrinterName="Recepção ' A", DocumentName='Recibo', UserName='Beth',
           Submitted='2026-10-23T10:00:00.0000000', JobStatus='Normal', TotalPages=2, PagesPrinted=1)


class TestPrintQueue(unittest.TestCase):
    def test_query_unicode_empty_single_and_failure(self):
        for raw, expected in [('', []), (json.dumps(JOB), [JOB]), ('[]', [])]:
            with self.subTest(raw=raw), patch.object(printing, 'is_windows_10_or_11', return_value=True), patch.object(
                printing.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=raw, stderr='')
            ) as run:
                self.assertEqual(printing.list_print_jobs(JOB['PrinterName']), (True, expected))
                command = base64.b64decode(run.call_args.args[0][-1]).decode('utf-16le')
                self.assertIn("Recepção '' A", command)
        with patch.object(printing, 'is_windows_10_or_11', return_value=True), patch.object(
            printing.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='Access denied')
        ):
            self.assertEqual(printing.list_print_jobs('A'), (False, 'Access denied'))
        with patch.object(printing, '_run', return_value=(True, '42')):
            self.assertFalse(printing.list_print_jobs('A')[0])

    def test_validation_platform_and_timeout(self):
        for job in [{}, dict(JOB, ID=True), dict(JOB, ID=-1), dict(JOB, Submitted='')]:
            with patch.object(printing, '_run') as run:
                self.assertFalse(printing.cancel_print_job(job)[0])
                run.assert_not_called()
        with patch('sys.platform', 'win32'), patch.object(printing, 'is_windows_10_or_11', return_value=False), patch.object(printing.subprocess, 'run') as run:
            self.assertFalse(printing.list_print_jobs('A')[0])
            run.assert_not_called()
        with patch.object(printing, 'is_windows_10_or_11', return_value=True), patch.object(
            printing.subprocess, 'run', side_effect=subprocess.TimeoutExpired('powershell', 20)
        ):
            self.assertIn('timed out', printing.cancel_print_job(JOB)[1])
        with patch('sys.platform', 'linux'), patch.object(printing, 'is_windows_10_or_11', return_value=False):
            with patch('shutil.which', return_value='/usr/bin/lpstat'), patch.object(
                printing.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='Printer1-10 beto 1024 Fri 24 Oct 10:00:00\n', stderr='')
            ):
                ok, jobs = printing.list_print_jobs('Printer1')
                self.assertTrue(ok)
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0]['ID'], 10)

    @unittest.skipUnless(os.name == 'nt', 'PowerShell behavioral test')
    def test_cancellation_script_rejects_changed_identity(self):
        # Execute the generated script with fake cmdlets: never touch a real queue.
        with patch.object(printing, '_run', return_value=(True, '')) as run:
            printing.cancel_print_job(JOB)
            script = run.call_args.args[0]
        for changed in (None, 'ID', 'PrinterName', 'DocumentName', 'UserName', 'Submitted', 'missing'):
            current = dict(JOB)
            if changed and changed != 'missing':
                current[changed] = 4 if changed == 'ID' else '2026-10-23T11:00:00.0000000' if changed == 'Submitted' else 'Changed'
            payload = base64.b64encode(json.dumps(current).encode()).decode()
            fixture = (
                "$ErrorActionPreference='Stop'; "
                f"$fixture=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) | ConvertFrom-Json; "
                "$fixture | Add-Member SubmittedTime ([datetime]::Parse($fixture.Submitted)); "
                "function Get-PrintJob {param($PrinterName,$ID) " + ("return $null" if changed == 'missing' else "return $fixture") + "}; "
                "function Remove-PrintJob {param($InputObject,$ErrorAction) Write-Output 'REMOVED'}; "
            )
            command = base64.b64encode((fixture + script).encode('utf-16le')).decode()
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', command],
                                    capture_output=True, text=True, timeout=20,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            with self.subTest(changed=changed):
                self.assertEqual('REMOVED' in result.stdout, changed is None, result.stderr)
                self.assertEqual(result.returncode == 0, changed is None)


class TestPrintPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = SimpleNamespace(language=InterfaceLanguage('pt'), windows_share_supported=True)
        self.panel = PrintQueuePanel(self.controller)
        self.addCleanup(self.panel.close)

    def wait_idle(self):
        deadline = time.monotonic() + 5
        while self.panel.running and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(self.panel.running)

    def test_async_refresh_selection_confirmation_and_failure(self):
        with patch('src.gui.printing.windows_share.list_printers', return_value=(True, [{'name': JOB['PrinterName']}])), patch(
            'src.gui.printing.printing.list_print_jobs', return_value=(True, [JOB])
        ):
            self.panel.refresh()
            self.assertFalse(self.panel.refresh_button.isEnabled())
            self.wait_idle()
        self.assertEqual(self.panel.table.item(0, 1).text(), 'Recibo')
        self.panel.table.selectRow(0)
        self.assertTrue(self.panel.cancel_button.isEnabled())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.No), patch.object(printing, 'cancel_print_job') as cancel:
            self.panel.cancel_selected()
            cancel.assert_not_called()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), patch.object(
            printing, 'cancel_print_job', return_value=(False, 'Access denied')
        ) as cancel:
            self.panel.cancel_selected()
            self.wait_idle()
            cancel.assert_called_once_with(JOB)
        self.assertEqual(self.panel.status.text(), 'Access denied')
        self.assertFalse(self.panel.cancel_button.isEnabled())
        self.assertEqual(self.panel.table.rowCount(), 0)
        self.controller.language.code = 'en'
        self.panel.retranslate()
        self.assertEqual(self.panel.refresh_button.text(), 'Refresh printers')

    def test_unsupported_and_query_error(self):
        self.panel.jobs_loaded((False, 'Spooler unavailable'))
        self.assertEqual(self.panel.status.text(), 'Spooler unavailable')
        self.panel.supported = False
        self.panel.update_actions()
        with patch.object(printing, 'list_print_jobs') as query:
            self.panel.refresh()
            query.assert_not_called()
        self.assertFalse(self.panel.refresh_button.isEnabled())
