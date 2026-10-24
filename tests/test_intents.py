"""Security boundary for explicitly enabled remote system commands."""

import base64
import http.client
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.core.access import hash_password, PERMISSIONS
from src.core.server import ServerManager
from src.core.intents import run_intent, IntentLimitError


class TestIntentAuthorization(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.server = ServerManager()
        self.addCleanup(self.server.stop_server)

    def start(self, **options):
        config = dict(enable_intents=True, auth_credentials=('admin', 'admin-secret'))
        config.update(options)
        return self.server.start_server('127.0.0.1', 0, self.directory.name, **config)

    def request(self, credentials=None, raw=None):
        headers = {'Content-Type': 'application/json'}
        if credentials:
            headers['Authorization'] = 'Basic ' + base64.b64encode(credentials.encode()).decode()
        connection = http.client.HTTPConnection('127.0.0.1', self.server.httpd.server_address[1], timeout=5)
        try:
            body = json.dumps({'command': 'echo authorized'}) if raw is None else raw
            connection.request('POST', '/api/intent', body, headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_enabled_intents_require_valid_general_credentials_before_binding(self):
        for credentials in (None, (), ('admin', ''), ('', 'secret'), 'invalid', (1, 'secret')):
            with self.subTest(credentials=credentials):
                ok, message = self.start(auth_credentials=credentials)
                self.assertFalse(ok)
                self.assertIn('administrator', message)
                self.assertIsNone(self.server.httpd)
                self.assertFalse(self.server.is_running)

    def test_missing_or_invalid_login_cannot_execute(self):
        self.assertTrue(self.start()[0])
        with patch('src.core.handlers.run_intent') as execute:
            for credentials in (None, 'admin:wrong', 'other:admin-secret'):
                self.assertEqual(self.request(credentials)[0], 401)
            execute.assert_not_called()

    def test_full_folder_permissions_do_not_grant_system_commands(self):
        ok, message = self.start(folder_users_enabled=True, folder_users=[{
            'name': 'operator', 'password': hash_password('folder-secret'),
            'grants': {'/': list(PERMISSIONS)},
        }])
        self.assertTrue(ok, message)
        with patch('src.core.handlers.run_intent') as execute:
            self.assertEqual(self.request('operator:folder-secret')[0], 403)
            execute.assert_not_called()

    def test_general_administrator_can_execute(self):
        self.assertTrue(self.start()[0])
        with patch('src.core.handlers.run_intent') as execute:
            execute.return_value = dict(stdout='authorized\n', stderr='', returncode=0)
            status, body = self.request('admin:admin-secret')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['stdout'], 'authorized\n')
            execute.assert_called_once()

    def test_runtime_configuration_without_login_is_denied(self):
        self.assertTrue(self.start()[0])
        self.server.httpd.app_config.pop('auth_credentials')
        with patch('src.core.handlers.run_intent') as execute:
            self.assertEqual(self.request()[0], 403)
            execute.assert_not_called()

    def test_disabled_intents_remain_unavailable_without_login(self):
        self.assertTrue(self.start(enable_intents=False, auth_credentials=None)[0])
        with patch('src.core.handlers.run_intent') as execute:
            self.assertEqual(self.request()[0], 405)
            execute.assert_not_called()

    def test_busy_command_slot_rejects_request_and_then_recovers(self):
        self.assertTrue(self.start()[0])
        self.server.httpd.intent_slot.acquire()
        try:
            with patch('src.core.handlers.run_intent') as execute:
                self.assertEqual(self.request('admin:admin-secret')[0], 503)
                execute.assert_not_called()
        finally:
            self.server.httpd.intent_slot.release()
        with patch('src.core.handlers.run_intent', return_value=dict(stdout='', stderr='', returncode=0)):
            self.assertEqual(self.request('admin:admin-secret')[0], 200)

    def test_failed_execution_releases_slot(self):
        self.assertTrue(self.start()[0])
        with patch('src.core.handlers.run_intent', side_effect=IntentLimitError('timed out')):
            self.assertEqual(self.request('admin:admin-secret')[0], 504)
        self.assertTrue(self.server.httpd.intent_slot.acquire(timeout=1))
        self.server.httpd.intent_slot.release()

    def test_invalid_and_oversized_bodies_cannot_execute(self):
        self.assertTrue(self.start()[0])
        with patch('src.core.handlers.run_intent') as execute:
            for body in (b'bad json', b'[]', b'{"command": 123}', b'{"command": ""}', b'\xff'):
                self.assertEqual(self.request('admin:admin-secret', raw=body)[0], 400)
            self.assertEqual(self.request('admin:admin-secret', raw=b'x' * 65537)[0], 413)
            execute.assert_not_called()


class TestIntentLimits(unittest.TestCase):
    def command(self, code):
        # list2cmdline is the Windows shell quoting used by this test host.
        if sys.platform == 'win32':
            return subprocess.list2cmdline([sys.executable, '-c', code])
        import shlex
        return shlex.join([sys.executable, '-c', code])

    def test_real_command_captures_both_streams_and_exit_status(self):
        result = run_intent(self.command("import sys; print('hello'); print('error', file=sys.stderr); sys.exit(3)"))
        self.assertEqual(result['stdout'].strip(), 'hello')
        self.assertEqual(result['stderr'].strip(), 'error')
        self.assertEqual(result['returncode'], 3)

    def test_real_command_timeout(self):
        with self.assertRaisesRegex(IntentLimitError, 'timed out'):
            run_intent(self.command('import time; time.sleep(10)'), timeout=0.2)

    def test_real_command_output_limit(self):
        with self.assertRaisesRegex(IntentLimitError, 'output exceeded'):
            run_intent(self.command("import sys; sys.stdout.write('x' * 1000000)"), output_limit=1024)
