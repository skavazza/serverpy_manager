import os
import subprocess
import tempfile
import unittest
import io
import stat
from threading import Event
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from src.core.ssh import (
    build_sftp_transfer, build_ssh_command, validate_ssh_target, ssh_check_connection,
    list_sftp_directory, sftp_transfer_with_password, ssh_open_terminal, ssh_run_command,
)
from src.gui.i18n import InterfaceLanguage
from src.gui.ssh_panel import SSHPanel, SFTPBrowserDialog, _SFTPTask


class TestSSHSupport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_validate_ssh_target_accepts_hostname_and_user(self):
        self.assertEqual(validate_ssh_target('example.com', 'dev', 2222), ('dev', 'example.com', 2222))
        self.assertEqual(validate_ssh_target('192.168.0.12', None, 22), (None, '192.168.0.12', 22))
        with self.assertRaises(ValueError):
            validate_ssh_target('http://bad-host', 'dev', 22)

    def test_ssh_check_uses_open_ssh_client_and_success_flag(self):
        with patch('src.core.ssh.shutil.which', return_value='/usr/bin/ssh'), patch('src.core.ssh.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess(args=['ssh'], returncode=0, stdout='__SSH_OK__\n', stderr='')
            ok, message = ssh_check_connection('example.com', 'dev', 2222, timeout=7)
            self.assertTrue(ok)
            self.assertIn('available', message.lower())
            self.assertIn('/usr/bin/ssh', run.call_args.args[0])

    def test_ssh_run_command_uses_remote_command_and_returns_output(self):
        with patch('src.core.ssh.shutil.which', return_value='/usr/bin/ssh'), patch('src.core.ssh.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess(args=['ssh'], returncode=0, stdout='Linux\n', stderr='')
            ok, output = ssh_run_command('example.com', 'dev', 2222, 'uname -a', timeout=9)
            self.assertTrue(ok)
            self.assertEqual(output, 'Linux')
            self.assertIn('uname -a', run.call_args.args[0])

    def test_selected_identity_is_used_by_all_ssh_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            identity = os.path.join(directory, 'private key')
            with open(identity, 'w', encoding='utf-8') as key_file:
                key_file.write('test identity')

            with patch('src.core.ssh.shutil.which', return_value='/usr/bin/ssh'), \
                    patch('src.core.ssh.subprocess.run') as run, \
                    patch('src.core.ssh.subprocess.Popen') as popen:
                run.return_value = subprocess.CompletedProcess(
                    args=['ssh'], returncode=0, stdout='__SSH_OK__\n', stderr='',
                )
                ok, _ = ssh_check_connection(
                    'example.com', 'dev', 2222, identity_file=identity,
                )
                self.assertTrue(ok)
                check_args = run.call_args.args[0]
                self.assertEqual(check_args[check_args.index('-i') + 1], identity)
                self.assertIn('IdentitiesOnly=yes', check_args)

                run.return_value = subprocess.CompletedProcess(
                    args=['ssh'], returncode=0, stdout='Linux\n', stderr='',
                )
                ok, _ = ssh_run_command(
                    'example.com', 'dev', 2222, 'uname -a', identity_file=identity,
                )
                self.assertTrue(ok)
                self.assertEqual(run.call_args.args[0][run.call_args.args[0].index('-i') + 1], identity)

                ssh_open_terminal('example.com', 'dev', 2222, identity_file=identity)
                terminal_args = popen.call_args.args[0]
                self.assertEqual(terminal_args[terminal_args.index('-i') + 1], identity)

                command = build_ssh_command(
                    'example.com', 'dev', 2222, 'uname -a', identity_file=identity,
                )
                self.assertEqual(command[command.index('-i') + 1], identity)

    def test_missing_identity_file_returns_visible_check_error(self):
        with patch('src.core.ssh.shutil.which', return_value='/usr/bin/ssh'), \
                patch('src.core.ssh.subprocess.run') as run:
            ok, message = ssh_check_connection(
                'example.com', identity_file='/missing/ssh-key',
            )
        self.assertFalse(ok)
        self.assertIn('identity file does not exist', message)
        run.assert_not_called()

    def test_password_connection_uses_reject_policy_without_agent_or_key_fallback(self):
        client = MagicMock()
        client.exec_command.return_value = (None, MagicMock(read=MagicMock(return_value=b'__SSH_OK__\n')), None)
        with patch('src.core.ssh.paramiko.SSHClient', return_value=client), \
                patch('src.core.ssh.paramiko.RejectPolicy') as reject_policy:
            ok, message = ssh_check_connection(
                'example.com', 'dev', 2222, auth_method='password', password='test-secret',
            )

        self.assertTrue(ok)
        self.assertIn('available', message)
        client.load_system_host_keys.assert_called_once_with()
        client.set_missing_host_key_policy.assert_called_once_with(reject_policy.return_value)
        client.connect.assert_called_once_with(
            hostname='example.com', port=2222, username='dev', password='test-secret',
            timeout=5, auth_timeout=5, banner_timeout=5,
            allow_agent=False, look_for_keys=False,
        )
        client.close.assert_called_once_with()

    def test_password_command_uses_paramiko_and_returns_remote_output(self):
        client = MagicMock()
        stdout = MagicMock()
        stdout.read.return_value = b'Linux\n'
        stdout.channel.recv_exit_status.return_value = 0
        stderr = MagicMock()
        stderr.read.return_value = b''
        client.exec_command.return_value = (None, stdout, stderr)
        with patch('src.core.ssh.paramiko.SSHClient', return_value=client), \
                patch('src.core.ssh.subprocess.run') as subprocess_run:
            result = ssh_run_command(
                'example.com', 'dev', 2222, 'uname -a',
                auth_method='password', password='test-secret',
            )

        self.assertEqual(result, (True, 'Linux'))
        client.exec_command.assert_called_once_with('uname -a', timeout=30)
        subprocess_run.assert_not_called()
        client.connect.assert_called_once()

    def test_password_sftp_listing_uses_paramiko(self):
        client = MagicMock()
        sftp = MagicMock()
        sftp.listdir_attr.return_value = [
            SimpleNamespace(filename='docs', st_mode=stat.S_IFDIR | 0o755),
            SimpleNamespace(filename='note.txt', st_mode=stat.S_IFREG | 0o644),
        ]
        client.open_sftp.return_value.__enter__.return_value = sftp
        with patch('src.core.ssh.paramiko.SSHClient', return_value=client):
            entries = list_sftp_directory(
                'example.com', 'dev', 22, None, '/home/dev',
                auth_method='password', password='test-secret',
            )
        self.assertEqual(entries, [
            {'name': 'docs', 'is_dir': True},
            {'name': 'note.txt', 'is_dir': False},
        ])
        sftp.listdir_attr.assert_called_once_with('/home/dev')
        client.close.assert_called_once_with()

    def test_password_sftp_transfer_reports_progress_and_uses_sftp_api(self):
        client = MagicMock()
        sftp = MagicMock()
        client.open_sftp.return_value.__enter__.return_value = sftp
        progress = MagicMock()
        with tempfile.TemporaryDirectory() as directory, \
                patch('src.core.ssh.paramiko.SSHClient', return_value=client):
            local_path = os.path.join(directory, 'source.txt')
            Path(local_path).write_text('data', encoding='utf-8')
            sftp.put.side_effect = lambda local, remote, callback: callback(4, 4)
            sftp_transfer_with_password(
                'example.com', 'dev', 22, 'test-secret', 'upload',
                local_path, '/remote/source.txt', Event(), progress,
            )
        sftp.put.assert_called_once_with(local_path, '/remote/source.txt', callback=sftp.put.call_args.kwargs['callback'])
        progress.assert_called_once_with(4, 4)
        client.close.assert_called_once_with()

    def test_password_auth_requires_username_and_password(self):
        with patch('src.core.ssh.paramiko.SSHClient') as ssh_client:
            ok, message = ssh_check_connection(
                'example.com', '', auth_method='password', password='test-secret',
            )
        self.assertFalse(ok)
        self.assertIn('username', message)
        ssh_client.assert_not_called()

    def test_password_terminal_prompts_interactively_without_receiving_password(self):
        with patch('src.core.ssh.shutil.which', return_value='/usr/bin/ssh'), \
                patch('src.core.ssh.subprocess.Popen') as popen:
            ssh_open_terminal(
                'example.com', 'dev', 2222, auth_method='password',
            )
        arguments = popen.call_args.args[0]
        self.assertIn('StrictHostKeyChecking=ask', arguments)
        self.assertIn('PreferredAuthentications=password,keyboard-interactive', arguments)
        self.assertIn('PubkeyAuthentication=no', arguments)
        self.assertNotIn('test-secret', arguments)

    def test_password_transfer_task_does_not_spawn_a_process_or_keep_password(self):
        task = _SFTPTask(
            None, None, 'upload',
            password_auth=(
                'example.com', 'dev', 22, 'test-secret',
                '/tmp/local.txt', '/remote/local.txt',
            ),
        )
        with patch('src.gui.ssh_panel.sftp_transfer_with_password') as transfer, \
                patch('src.gui.ssh_panel.subprocess.Popen') as popen:
            task.run()

        transfer.assert_called_once()
        self.assertEqual(transfer.call_args.args[:6], (
            'example.com', 'dev', 22, 'test-secret', 'upload', '/tmp/local.txt',
        ))
        popen.assert_not_called()
        self.assertIsNone(task.password_auth)

    def test_sftp_builder_quotes_paths_and_uses_selected_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            local_path = os.path.join(directory, 'local file.txt')
            identity = os.path.join(directory, 'identity')
            Path(local_path).write_text('payload', encoding='utf-8')
            Path(identity).write_text('key', encoding='utf-8')
            with patch('src.core.ssh.shutil.which', side_effect=lambda name: '/usr/bin/sftp' if name == 'sftp' else None):
                arguments, batch = build_sftp_transfer(
                    'example.com', 'dev', 2222, identity, 'upload',
                    local_path, '/remote folder/file "one".txt',
                )

        self.assertEqual(arguments[0], '/usr/bin/sftp')
        self.assertEqual(arguments[1:3], ['-b', '-'])
        self.assertIn('-P', arguments)
        self.assertEqual(arguments[arguments.index('-i') + 1], identity)
        self.assertIn('IdentitiesOnly=yes', arguments)
        self.assertIn('"', batch)
        self.assertTrue(batch.startswith('put '))
        self.assertTrue(batch.endswith('\n'))

    def test_sftp_builder_rejects_batch_injection_and_missing_local_source(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('src.core.ssh.shutil.which', return_value='/usr/bin/sftp'):
                with self.assertRaisesRegex(ValueError, 'without line breaks'):
                    build_sftp_transfer(
                        'example.com', None, 22, None, 'download',
                        os.path.join(directory, 'target'), '/remote/file\nquit',
                    )
                with self.assertRaisesRegex(FileNotFoundError, 'existing local file'):
                    build_sftp_transfer(
                        'example.com', None, 22, None, 'upload',
                        os.path.join(directory, 'missing'), '/remote/file',
                    )

    def test_sftp_directory_listing_parses_directories_and_files(self):
        output = (
            'drwxr-xr-x 2 dev users 4096 Oct 23 20:33 project folder\n'
            '-rw-r--r-- 1 dev users  123 Oct 23 20:34 report final.txt\n'
            'lrwxrwxrwx 1 dev users   11 Oct 23 20:35 latest -> report final.txt\n'
        )
        with patch('src.core.ssh.shutil.which', side_effect=lambda name: '/usr/bin/sftp' if name == 'sftp' else None), \
                patch('src.core.ssh.subprocess.run', return_value=subprocess.CompletedProcess(
                    args=['sftp'], returncode=0, stdout=output, stderr='',
                )) as run:
            entries = list_sftp_directory('example.com', 'dev', 2222, None, '/home/dev')

        self.assertEqual(entries, [
            {'name': 'project folder', 'is_dir': True},
            {'name': 'latest -> report final.txt', 'is_dir': False},
            {'name': 'report final.txt', 'is_dir': False},
        ])
        self.assertEqual(run.call_args.kwargs['input'], 'ls -la "/home/dev"\n')

    def test_sftp_directory_listing_surfaces_remote_errors(self):
        with patch('src.core.ssh.shutil.which', side_effect=lambda name: '/usr/bin/sftp' if name == 'sftp' else None), \
                patch('src.core.ssh.subprocess.run', return_value=subprocess.CompletedProcess(
                    args=['sftp'], returncode=1, stdout='', stderr='Permission denied',
                )):
            with self.assertRaisesRegex(OSError, 'Permission denied'):
                list_sftp_directory('example.com', None, 22, None, '/restricted')

    def test_sftp_download_replaces_destination_only_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'download.txt'
            temporary = Path(directory) / '.download.part'
            destination.write_text('old', encoding='utf-8')
            temporary.write_text('new', encoding='utf-8')
            process = MagicMock()
            process.stdin = io.StringIO()
            process.returncode = 0
            process.poll.return_value = 0
            process.communicate.return_value = ('', None)
            task = _SFTPTask(['sftp'], 'get remote local\n', 'download', str(temporary), str(destination))

            with patch('src.gui.ssh_panel.subprocess.Popen', return_value=process):
                task.run()

            self.assertEqual(destination.read_text(encoding='utf-8'), 'new')
            self.assertFalse(temporary.exists())

    def test_sftp_cancel_preserves_existing_download_and_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'download.txt'
            temporary = Path(directory) / '.download.part'
            destination.write_text('old', encoding='utf-8')
            temporary.write_text('partial', encoding='utf-8')
            process = MagicMock()
            process.stdin = io.StringIO()
            process.poll.return_value = None
            process.wait.return_value = -15
            process.communicate.return_value = ('', None)
            process.terminate.side_effect = lambda: setattr(process, 'returncode', -15)
            task = _SFTPTask(['sftp'], 'get remote local\n', 'download', str(temporary), str(destination))
            task.cancel()

            with patch('src.gui.ssh_panel.subprocess.Popen', return_value=process):
                task.run()

            self.assertEqual(destination.read_text(encoding='utf-8'), 'old')
            self.assertFalse(temporary.exists())

    def test_connection_check_runs_in_background_and_reenables_controls(self):
        panel = SSHPanel(SimpleNamespace(settings=None, language=InterfaceLanguage()))
        tasks = []
        with patch('src.gui.ssh_panel.QThreadPool.globalInstance') as pool, \
                patch('src.gui.ssh_panel.ssh_check_connection', return_value=(True, 'SSH connection is available.')) as check:
            pool.return_value.start.side_effect = tasks.append
            panel.check_connection()

            check.assert_not_called()
            self.assertTrue(panel.running)
            self.assertFalse(panel.host.isEnabled())
            self.assertEqual(len(tasks), 1)

            tasks[0].run()

        check.assert_called_once_with(
            'localhost', '', 22, identity_file=None,
            auth_method='key', password=None,
        )
        self.assertFalse(panel.running)
        self.assertTrue(panel.host.isEnabled())
        self.assertEqual(panel.status.text(), 'SSH connection is available.')
        panel.close()

    def test_remote_command_runs_in_background_and_updates_status(self):
        panel = SSHPanel(SimpleNamespace(settings=None, language=InterfaceLanguage()))
        panel.command.setText('uname -a')
        tasks = []
        with patch('src.gui.ssh_panel.QThreadPool.globalInstance') as pool, \
                patch('src.gui.ssh_panel.ssh_run_command', return_value=(True, 'first line\nsecond line\nliteral {value}')) as run:
            pool.return_value.start.side_effect = tasks.append
            panel.run_command()

            run.assert_not_called()
            self.assertTrue(panel.running)
            self.assertFalse(panel.command.isEnabled())
            tasks[0].run()

        run.assert_called_once_with(
            'localhost', '', 22, 'uname -a', identity_file=None,
            auth_method='key', password=None,
        )
        self.assertFalse(panel.running)
        self.assertEqual(panel.output.toPlainText(), 'first line\nsecond line\nliteral {value}')
        self.assertEqual(panel.status.text(), 'Remote command completed.')
        self.assertTrue(panel.copy_output_button.isEnabled())
        self.assertTrue(panel.clear_output_button.isEnabled())
        panel.copy_output()
        self.assertEqual(QApplication.clipboard().text(), panel.output.toPlainText())
        panel.clear_output()
        self.assertEqual(panel.output.toPlainText(), '')
        self.assertFalse(panel.copy_output_button.isEnabled())
        panel.close()

    def test_remote_command_failure_is_shown_in_output_area(self):
        panel = SSHPanel(SimpleNamespace(settings=None, language=InterfaceLanguage()))
        tasks = []
        with patch('src.gui.ssh_panel.QThreadPool.globalInstance') as pool, \
                patch('src.gui.ssh_panel.ssh_run_command', return_value=(False, 'permission denied\ncheck your key')):
            pool.return_value.start.side_effect = tasks.append
            panel.run_command()
            tasks[0].run()

        self.assertEqual(panel.output.toPlainText(), 'permission denied\ncheck your key')
        self.assertEqual(panel.status.text(), 'Remote command failed.')
        panel.close()

    def test_ssh_panel_retranslates_controls_and_status(self):
        language = InterfaceLanguage('pt')
        panel = SSHPanel(SimpleNamespace(settings=None, language=language))
        self.assertEqual(panel.host_combo.itemText(0), 'Host manual')
        self.assertEqual(panel.check_button.text(), 'Testar SSH')
        self.assertEqual(panel.identity_button.text(), 'Selecionar chave...')
        self.assertEqual(panel.clear_identity_button.text(), 'Limpar')
        self.assertEqual(panel.copy_output_button.text(), 'Copiar saída')
        self.assertEqual(panel.clear_output_button.text(), 'Limpar saída')
        panel._set_status('Checking SSH...')
        self.assertEqual(panel.status.text(), 'Verificando SSH...')
        panel.close()

    def test_saved_host_persists_and_restores_identity_path(self):
        settings = MagicMock()
        settings.value.return_value = []
        panel = SSHPanel(SimpleNamespace(settings=settings, language=InterfaceLanguage()))
        panel.host.setText('example.com')
        panel.username.setText('dev')
        panel.identity_file.setText('/keys/team key')
        panel.save_host()

        saved_hosts = settings.setValue.call_args.args[1]
        self.assertEqual(saved_hosts[0]['identity_file'], '/keys/team key')

        settings.value.return_value = saved_hosts
        restored = SSHPanel(SimpleNamespace(settings=settings, language=InterfaceLanguage()))
        restored.apply_saved_host(1)
        self.assertEqual(restored.identity_file.text(), '/keys/team key')
        panel.close()
        restored.close()

    def test_password_authentication_is_not_saved_and_is_cleared_on_host_switch(self):
        settings = MagicMock()
        settings.value.return_value = []
        panel = SSHPanel(SimpleNamespace(settings=settings, language=InterfaceLanguage()))
        panel.host.setText('example.com')
        panel.username.setText('dev')
        panel.auth_method.setCurrentIndex(panel.auth_method.findData('password'))
        panel.password.setText('test-secret')
        self.assertFalse(panel.password.isHidden())
        self.assertTrue(panel.key_row_widget.isHidden())
        self.assertEqual(panel._authentication(), ('password', None, 'test-secret'))

        panel.save_host()
        saved_hosts = settings.setValue.call_args.args[1]
        self.assertNotIn('password', saved_hosts[0])
        self.assertEqual(saved_hosts[0]['auth_method'], 'password')

        settings.value.return_value = saved_hosts
        restored = SSHPanel(SimpleNamespace(settings=settings, language=InterfaceLanguage()))
        restored.password.setText('another-secret')
        restored.apply_saved_host(1)
        self.assertEqual(restored.auth_method.currentData(), 'password')
        self.assertEqual(restored.password.text(), '')
        panel.close()
        restored.close()

    def test_selecting_identity_uses_file_dialog_and_cancel_keeps_current_value(self):
        panel = SSHPanel(SimpleNamespace(settings=None, language=InterfaceLanguage()))
        with patch('src.gui.ssh_panel.QFileDialog.getOpenFileName', return_value=('/keys/id_ed25519', '')):
            panel.select_identity_file()
        self.assertEqual(panel.identity_file.text(), '/keys/id_ed25519')

        with patch('src.gui.ssh_panel.QFileDialog.getOpenFileName', return_value=('', '')):
            panel.select_identity_file()
        self.assertEqual(panel.identity_file.text(), '/keys/id_ed25519')
        panel.close()

    def test_upload_requires_confirmation_and_runs_sftp_in_background(self):
        panel = SSHPanel(SimpleNamespace(settings=None, language=InterfaceLanguage()))
        tasks = []
        with patch('src.gui.ssh_panel.QFileDialog.getOpenFileName', return_value=('/tmp/input.txt', '')), \
                patch('src.gui.ssh_panel.build_sftp_transfer', return_value=(['sftp'], 'put source target\n')) as build, \
                patch('src.gui.ssh_panel.QMessageBox.question', return_value=QMessageBox.Yes) as confirm, \
                patch('src.gui.ssh_panel.QThreadPool.globalInstance') as pool:
            pool.return_value.start.side_effect = tasks.append
            panel.upload_file()

        self.assertEqual(panel.remote_file.text(), 'input.txt')
        confirm.assert_called_once()
        build.assert_called_once_with(
            'localhost', '', 22, None, 'upload', '/tmp/input.txt', 'input.txt',
        )
        self.assertTrue(panel.running)
        self.assertTrue(panel.cancel_transfer_button.isEnabled())
        self.assertFalse(panel.transfer_progress.isHidden())
        self.assertEqual(len(tasks), 1)
        panel.cancel_transfer()
        self.assertTrue(tasks[0].cancelled.is_set())
        self.assertFalse(panel.cancel_transfer_button.isEnabled())
        panel.close()

    def test_upload_cancelled_at_overwrite_prompt_does_not_start_transfer(self):
        panel = SSHPanel(SimpleNamespace(settings=None, language=InterfaceLanguage()))
        with patch('src.gui.ssh_panel.QFileDialog.getOpenFileName', return_value=('/tmp/input.txt', '')), \
                patch('src.gui.ssh_panel.build_sftp_transfer', return_value=(['sftp'], 'put source target\n')), \
                patch('src.gui.ssh_panel.QMessageBox.question', return_value=QMessageBox.No), \
                patch('src.gui.ssh_panel.QThreadPool.globalInstance') as pool:
            panel.upload_file()

        pool.return_value.start.assert_not_called()
        self.assertFalse(panel.running)
        panel.close()

    def test_sftp_browser_selects_remote_files_and_navigates_directories(self):
        controller = SimpleNamespace(language=InterfaceLanguage())
        tasks = []
        with patch('src.gui.ssh_panel.QThreadPool.globalInstance') as pool:
            pool.return_value.start.side_effect = tasks.append
            dialog = SFTPBrowserDialog(
                controller, ('example.com', 'dev', 2222, None, 'key', None),
            )
        self.assertFalse(dialog.back_button.isEnabled())
        self.assertFalse(dialog.forward_button.isEnabled())
        self.assertFalse(dialog.up_button.isEnabled())
        dialog.listing_finished((True, [
            {'name': 'folder with spaces', 'is_dir': True},
            {'name': 'report final.txt', 'is_dir': False},
        ]))
        folder = dialog.entries.topLevelItem(0)
        file_item = dialog.entries.topLevelItem(1)
        self.assertEqual(folder.text(0), 'folder with spaces')
        self.assertEqual(file_item.text(0), 'report final.txt')
        self.assertFalse(dialog.use_button.isEnabled())

        dialog.entries.setCurrentItem(folder)
        self.assertFalse(dialog.use_button.isEnabled())
        with patch('src.gui.ssh_panel.QThreadPool.globalInstance') as pool:
            pool.return_value.start.side_effect = tasks.append
            dialog.open_entry(folder, 0)
        self.assertEqual(dialog.remote_path, '/folder with spaces')
        self.assertFalse(dialog.back_button.isEnabled())
        self.assertFalse(dialog.up_button.isEnabled())

        dialog.listing_finished((True, [
            {'name': 'nested.txt', 'is_dir': False},
        ]))
        self.assertTrue(dialog.back_button.isEnabled())
        self.assertTrue(dialog.up_button.isEnabled())
        dialog.entries.setCurrentItem(dialog.entries.topLevelItem(0))
        self.assertTrue(dialog.use_button.isEnabled())
        dialog.select_file()
        self.assertEqual(dialog.selected_path, '/folder with spaces/nested.txt')
        dialog.close()
        self.assertEqual(len(tasks), 2)

    def test_sftp_browser_back_and_forward_navigation(self):
        controller = SimpleNamespace(language=InterfaceLanguage())
        tasks = []
        with patch('src.gui.ssh_panel.QThreadPool.globalInstance') as pool:
            pool.return_value.start.side_effect = tasks.append
            dialog = SFTPBrowserDialog(
                controller, ('example.com', 'dev', 2222, None, 'key', None),
            )
            dialog.listing_finished((True, []))

            dialog.navigate_directory('/var/www')
            dialog.listing_finished((True, []))
            dialog.navigate_directory('/var/www/html')
            dialog.listing_finished((True, []))
            dialog.back_button.click()
            self.assertEqual(dialog.remote_path, '/var/www')
            self.assertFalse(dialog.back_button.isEnabled())
            self.assertFalse(dialog.forward_button.isEnabled())
            dialog.listing_finished((True, []))
            self.assertTrue(dialog.back_button.isEnabled())
            self.assertTrue(dialog.forward_button.isEnabled())

            dialog.forward_button.click()
            self.assertEqual(dialog.remote_path, '/var/www/html')
            dialog.listing_finished((True, []))
            dialog.back_button.click()
            dialog.listing_finished((True, []))
            dialog.path.setText('/opt')
            dialog.go_button.click()
            self.assertEqual(dialog.remote_path, '/opt')
            dialog.listing_finished((True, []))
            self.assertFalse(dialog.forward_button.isEnabled())
            self.assertEqual(len(tasks), 7)
        dialog.close()

    def test_panel_browser_populates_remote_file_field(self):
        panel = SSHPanel(SimpleNamespace(settings=None, language=InterfaceLanguage()))
        dialog = MagicMock()
        dialog.exec.return_value = QDialog.Accepted
        dialog.selected_path = '/home/dev/report.txt'
        with patch('src.gui.ssh_panel.SFTPBrowserDialog', return_value=dialog) as browser:
            panel.browse_remote_file()
        self.assertEqual(panel.remote_file.text(), '/home/dev/report.txt')
        browser.assert_called_once_with(
            panel.controller, ('localhost', '', 22, None, 'key', None), panel,
        )
        panel.close()

    def test_download_confirms_overwrite_and_uses_temporary_destination(self):
        panel = SSHPanel(SimpleNamespace(settings=None, language=InterfaceLanguage()))
        tasks = []
        with tempfile.TemporaryDirectory() as directory:
            destination = os.path.join(directory, 'download.txt')
            Path(destination).write_text('existing', encoding='utf-8')
            panel.remote_file.setText('/remote/download.txt')
            with patch('src.gui.ssh_panel.QFileDialog.getSaveFileName', return_value=(destination, '')) as choose, \
                    patch('src.gui.ssh_panel.build_sftp_transfer', return_value=(['sftp'], 'get remote local\n')) as build, \
                    patch('src.gui.ssh_panel.QMessageBox.question', return_value=QMessageBox.Yes) as confirm, \
                    patch('src.gui.ssh_panel.QThreadPool.globalInstance') as pool:
                pool.return_value.start.side_effect = tasks.append
                panel.download_file()

            choose.assert_called_once()
            confirm.assert_called_once()
            arguments = build.call_args.args
            self.assertEqual(arguments[:5], ('localhost', '', 22, None, 'download'))
            self.assertNotEqual(arguments[5], destination)
            self.assertTrue(os.path.exists(arguments[5]))
            self.assertEqual(Path(destination).read_text(encoding='utf-8'), 'existing')
            self.assertEqual(tasks[0].destination, destination)
            self.assertEqual(tasks[0].temporary_path, arguments[5])
            Path(arguments[5]).unlink()
        panel.close()
