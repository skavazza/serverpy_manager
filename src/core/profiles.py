"""Versioned local profiles, validated before any settings are applied."""

import copy
import ipaddress
import json
import os

from .access import validate_users, validate_access_config
from .shares import validate_shared_folders
from .response_headers import validate_response_headers

CHECKS = ('chk_render_pages', 'chk_allow_mod', 'chk_intent', 'chk_auth', 'chk_whitelist',
          'chk_tls', 'chk_verify_header', 'chk_rate_limit', 'chk_custom_charset',
          'chk_custom_headers', 'groupBox_schedule')
TEXTS = ('line_whitelist', 'line_rate_limit', 'line_custom_charset', 'time_start', 'time_stop', 'certificate')


def validate_profile(data, check_paths=False):
    if not isinstance(data, dict) or set(data) - {'root_folder', 'port', 'interface', 'options', 'camera'}:
        raise ValueError('Invalid configuration profile.')
    value = copy.deepcopy(data)
    root, port, interface, options = (value.get(key) for key in ('root_folder', 'port', 'interface', 'options'))
    if not isinstance(root, str) or not os.path.isabs(root) or (check_paths and not os.path.isdir(root)):
        raise ValueError('The profile root folder is unavailable.')
    if not isinstance(port, str) or not port.isascii() or not port.isdigit() or len(port) > 5 or not 0 <= int(port) <= 65535:
        raise ValueError('Invalid profile port.')
    try:
        ipaddress.ip_address(interface)
    except (ValueError, TypeError):
        raise ValueError('Invalid profile network interface.') from None
    allowed = set(CHECKS + TEXTS) | {'cors', 'redirections', 'custom_headers', 'shared_folders', 'folder_users', 'folder_users_enabled'}
    if not isinstance(options, dict) or set(options) - allowed:
        raise ValueError('Invalid profile options.')
    for key in CHECKS + ('folder_users_enabled',):
        if key in options and type(options[key]) is not bool:
            raise ValueError('Invalid profile options.')
    for key in TEXTS:
        if key in options and not isinstance(options[key], str):
            raise ValueError('Invalid profile options.')
    for key in ('time_start', 'time_stop'):
        if key in options:
            import datetime
            try:
                datetime.time.fromisoformat(options[key])
            except ValueError:
                raise ValueError('Invalid profile schedule.') from None
    if options.get('chk_rate_limit') and (not options.get('line_rate_limit', '').isascii() or not options.get('line_rate_limit', '').isdigit() or int(options['line_rate_limit']) < 1):
        raise ValueError('Invalid profile request limit.')
    if options.get('chk_whitelist'):
        try:
            for address in options.get('line_whitelist', '').split(','):
                ipaddress.ip_address(address.strip())
        except ValueError:
            raise ValueError('Invalid profile IP allowlist.') from None
    if options.get('chk_custom_charset'):
        import codecs
        try:
            codecs.lookup(options.get('line_custom_charset', ''))
        except LookupError:
            raise ValueError('Invalid profile character encoding.') from None
    options['shared_folders'] = validate_shared_folders(options.get('shared_folders', []), check_paths)
    options['folder_users'] = validate_users(options.get('folder_users', []))
    options['custom_headers'] = validate_response_headers(options.get('custom_headers', {}))
    cors = options.get('cors', {'origin': '*', 'methods': 'GET, POST, OPTIONS, PUT, DELETE', 'headers': 'Content-Type, Authorization'})
    if not isinstance(cors, dict) or any(not isinstance(cors.get(key), str) for key in ('origin', 'methods', 'headers')):
        raise ValueError('Invalid profile CORS settings.')
    options['cors'] = cors
    redirects = options.get('redirections', [])
    if not isinstance(redirects, list) or any(not isinstance(row, (tuple, list)) or len(row) != 3 or not isinstance(row[0], str) or not isinstance(row[1], str) or row[2] not in (301, 302, 303, 307, 308) for row in redirects):
        raise ValueError('Invalid profile redirections.')
    options['redirections'] = redirects
    if check_paths and options.get('chk_tls') and not os.path.isfile(options.get('certificate', '')):
        raise ValueError('The profile TLS certificate is unavailable.')
    validation = dict(shared_folders=options['shared_folders'], folder_users=options['folder_users'], folder_users_enabled=options.get('folder_users_enabled', False))
    validate_access_config(validation, root)
    camera = value.setdefault('camera', {'fps': 5, 'quality': 75, 'resolution_width': 960})
    if not isinstance(camera, dict) or set(camera) != {'fps', 'quality', 'resolution_width'} or any(type(item) is not int for item in camera.values()) or not 1 <= camera['fps'] <= 30 or not 10 <= camera['quality'] <= 95 or camera['resolution_width'] not in (320, 640, 960, 1280, 1920):
        raise ValueError('Invalid profile camera settings.')
    return value


class ProfileStore:
    def __init__(self, settings):
        self.settings = settings

    def read(self):
        raw = self.settings.value('profiles/data', '{"version":1,"items":{}}')
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('items'), dict) or len(data['items']) > 32:
                raise ValueError()
            return {self.name(name): validate_profile(profile) for name, profile in data['items'].items()}
        except (ValueError, TypeError, AttributeError):
            raise ValueError('Unable to read saved profiles. Existing data was preserved.') from None

    @staticmethod
    def name(name):
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60 or any(ord(char) < 32 for char in name):
            raise ValueError('Use a profile name with 1 to 60 characters.')
        return name.strip()

    def write(self, items):
        self.settings.setValue('profiles/data', json.dumps({'version': 1, 'items': items}, ensure_ascii=False))
        self.settings.sync()
        status = self.settings.status()
        if getattr(status, 'value', status) != 0:
            raise ValueError('Unable to save configuration profiles.')

    def save(self, name, profile):
        name, profile = self.name(name), validate_profile(profile, check_paths=True)
        items = self.read()
        if name not in items and len(items) >= 32:
            raise ValueError('Configure at most 32 profiles.')
        items[name] = profile
        self.write(items)

    def delete(self, name):
        items = self.read()
        del items[name]
        self.write(items)
