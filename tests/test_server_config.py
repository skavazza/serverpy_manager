"""Runtime configuration snapshots must preserve toggles and access boundaries."""

from types import SimpleNamespace
import unittest

from src.gui.server_config import build_server_config, ServerConfigurationError


class Field:
    def __init__(self, value):
        self.value = value

    def text(self):
        return self.value

    def isChecked(self):
        return bool(self.value)


class TestServerConfiguration(unittest.TestCase):
    def setUp(self):
        values = dict(chk_tls=False, chk_render_pages=True, chk_allow_mod=False,
                      chk_intent=False, chk_verify_header=True, chk_cloudflare_tunnel=False,
                      chk_custom_headers=False, chk_auth=False, chk_whitelist=False,
                      chk_rate_limit=False, chk_custom_charset=False,
                      line_cloudflare_hostname=' Arquivos.Example.com. ',
                      line_username='admin', line_password='not-enabled',
                      line_whitelist='127.0.0.1, ::1', line_rate_limit='20',
                      line_custom_charset=' utf-8 ')
        self.window = SimpleNamespace(**{key: Field(value) for key, value in values.items()})
        self.controller = SimpleNamespace(window=self.window, cert_path='certificate.pem',
            cors_config={'origin': '*'}, custom_headers={'X-Test': 'value'},
            redirections=[['/old', '/new', 302]], shared_folders=[{'name': 'docs', 'path': 'docs', 'writable': False}],
            folder_users=[{'name': 'reader', 'grants': {'/': ['view']}}], folder_users_enabled=True)

    def test_disabled_features_do_not_include_stale_credentials_or_optional_settings(self):
        config = build_server_config(self.controller)
        for key in ('auth_credentials', 'whitelist', 'rate_limit', 'custom_charset'):
            self.assertNotIn(key, config)
        self.assertEqual(config['custom_headers'], {})
        self.assertEqual(config['cloudflare_hostname'], 'arquivos.example.com')
        self.assertFalse(config['allow_mod'])
        self.assertTrue(config['folder_users_enabled'])

    def test_snapshot_does_not_change_when_interface_settings_change(self):
        config = build_server_config(self.controller)
        self.controller.folder_users[0]['grants']['/'].append('delete')
        self.controller.shared_folders[0]['writable'] = True
        self.controller.cors_config['origin'] = 'changed'
        self.controller.redirections[0][1] = '/changed'
        self.assertEqual(config['folder_users'][0]['grants']['/'], ['view'])
        self.assertFalse(config['shared_folders'][0]['writable'])
        self.assertEqual(config['cors_config']['origin'], '*')
        self.assertEqual(config['redirections'][0][1], '/new')

    def test_intents_require_enabled_general_login_and_preserve_optional_values(self):
        self.window.chk_intent.value = True
        with self.assertRaisesRegex(ServerConfigurationError, 'administrator'):
            build_server_config(self.controller)
        for name in ('chk_auth', 'chk_whitelist', 'chk_rate_limit', 'chk_custom_charset', 'chk_custom_headers'):
            getattr(self.window, name).value = True
        config = build_server_config(self.controller)
        self.assertEqual(config['auth_credentials'], ('admin', 'not-enabled'))
        self.assertEqual(config['whitelist'], ['127.0.0.1', '::1'])
        self.assertEqual(config['rate_limit'], 20)
        self.assertEqual(config['custom_charset'], 'utf-8')
        self.assertEqual(config['custom_headers'], {'X-Test': 'value'})
