import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import venv

import setup_env

BASH = shutil.which('bash')
if BASH is None and Path('C:/Program Files/Git/bin/bash.exe').is_file():
    BASH = 'C:/Program Files/Git/bin/bash.exe'


class TestEnvironmentSetup(unittest.TestCase):
    def test_checks_all_direct_packages_including_qrcode_and_paramiko(self):
        versions = setup_env.pinned_versions()
        def installed(name):
            if name in ('qrcode', 'paramiko'):
                raise setup_env.metadata.PackageNotFoundError(name)
            return versions[name]
        with patch.object(setup_env.metadata, 'version', side_effect=installed), patch.object(setup_env.importlib, 'import_module') as imports:
            problems = setup_env.check_environment()
        self.assertTrue(any('qrcode' in item for item in problems))
        self.assertTrue(any('paramiko' in item for item in problems))
        imports.assert_not_called()

    def test_import_errors_are_reported_even_when_versions_match(self):
        with patch.object(setup_env.metadata, 'version', side_effect=setup_env.pinned_versions().__getitem__), patch.object(setup_env.importlib, 'import_module', side_effect=ImportError('DLL missing')):
            problems = setup_env.check_environment()
        self.assertTrue(any('DLL missing' in item for item in problems))

    def test_failed_install_stops_without_rechecking_or_starting_app(self):
        with patch.object(setup_env, 'check_environment', return_value=['Missing qrcode']), patch.object(setup_env.sys, 'argv', ['setup_env.py']), patch.object(setup_env.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            run.return_value.returncode = 17
            self.assertEqual(setup_env.main(), 17)
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0][:4], [setup_env.sys.executable, '-m', 'pip', 'install'])

    def test_successful_install_checks_again_in_a_fresh_process(self):
        with patch.object(setup_env, 'check_environment', return_value=['Missing dependency']), patch.object(setup_env.sys, 'argv', ['setup_env.py']), patch.object(setup_env.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            run.return_value.returncode = 0
            self.assertEqual(setup_env.main(), 0)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][-1], '--check')

    def test_check_mode_does_not_install(self):
        with patch.object(setup_env, 'check_environment', return_value=['Missing dependency']), patch.object(setup_env.sys, 'argv', ['setup_env.py', '--check']), patch.object(setup_env.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(setup_env.main(), 1)
            run.assert_not_called()


@unittest.skipUnless(os.name == 'nt', 'Windows launcher requires cmd.exe')
class TestWindowsLauncher(unittest.TestCase):
    def test_failed_dependency_setup_never_launches_application(self):
        with tempfile.TemporaryDirectory(prefix='serverpy launcher ') as scratch:
            root = Path(scratch)
            shutil.copyfile('start.bat', root / 'start.bat')
            venv.EnvBuilder(with_pip=False).create(root / 'venv')
            (root / 'setup_env.py').write_text('raise SystemExit(17)', encoding='utf-8')
            result = subprocess.run(['cmd.exe', '/d', '/c', 'start.bat'], cwd=root,
                                    capture_output=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(b'Iniciando ServerPy', result.stdout)
            self.assertTrue((root / 'venv').is_dir())

    def test_check_mode_propagates_failure_and_preserves_incompatible_venv(self):
        with tempfile.TemporaryDirectory(prefix='serverpy launcher ') as scratch:
            root = Path(scratch)
            shutil.copyfile('start.bat', root / 'start.bat')
            (root / 'venv').mkdir()
            marker = root / 'venv' / 'preserved.txt'
            marker.write_text('keep')
            result = subprocess.run(['cmd.exe', '/d', '/c', 'start.bat', '--check'], cwd=root,
                                    capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(), 'keep')


@unittest.skipUnless(BASH, 'Bash is required to exercise start.sh')
class TestBashLauncher(unittest.TestCase):
    def test_dependency_failure_stops_before_launch_in_a_path_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix='serverpy launcher ') as scratch:
            root = Path(scratch)
            shutil.copyfile('start.sh', root / 'start.sh')
            interpreter = root / 'venv' / 'bin' / 'python'
            interpreter.parent.mkdir(parents=True)
            interpreter.write_bytes(b'#!/bin/sh\nif [ "$1" = "-c" ]; then exit 0; fi\necho "setup failed"\nexit 17\n')
            interpreter.chmod(0o755)
            result = subprocess.run([BASH, 'start.sh'], cwd=root, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
            self.assertIn(b'setup failed', result.stdout)
            self.assertNotIn(b'Iniciando ServerPy', result.stdout)

    def test_invalid_environment_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix='serverpy launcher ') as scratch:
            root = Path(scratch)
            shutil.copyfile('start.sh', root / 'start.sh')
            (root / 'venv').mkdir()
            marker = root / 'venv' / 'preserved.txt'
            marker.write_text('keep')
            result = subprocess.run([BASH, 'start.sh'], cwd=root, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(), 'keep')
