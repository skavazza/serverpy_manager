"""Local account hashes and explicit permissions for published HTTP roots."""

import base64
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets

PERMISSIONS = ('view', 'download', 'upload', 'edit', 'delete')
ROUNDS = 200_000


def hash_password(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 1024:
        raise ValueError('Use a password with 8 to 1024 characters.')
    salt = secrets.token_hex(16)
    return {'salt': salt, 'digest': hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), ROUNDS).hex()}


def verify_password(password, record):
    if not isinstance(password, str) or len(password) > 1024:
        return False
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(record['salt']), ROUNDS).hex()
    return hmac.compare_digest(digest, record['digest'])


def validate_users(users, roots=None):
    if not isinstance(users, list) or len(users) > 32:
        raise ValueError('Configure at most 32 folder users.')
    result, names = [], set()
    for user in users:
        if not isinstance(user, dict):
            raise ValueError('Invalid folder user configuration.')
        name, password, grants = user.get('name'), user.get('password'), user.get('grants')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,40}', name) or name.casefold() in names:
            raise ValueError('Use a unique user name with 1 to 40 letters, numbers, dots, hyphens or underscores.')
        if not isinstance(password, dict) or not re.fullmatch('[0-9a-f]{32}', str(password.get('salt', ''))) or not re.fullmatch('[0-9a-f]{64}', str(password.get('digest', ''))):
            raise ValueError('Invalid stored password hash.')
        if not isinstance(grants, dict) or len(grants) > 33:
            raise ValueError('Invalid folder permissions.')
        checked = {}
        for root, allowed in grants.items():
            if not isinstance(root, str) or (roots is not None and root not in roots):
                raise ValueError('A user permission refers to an unknown folder.')
            if not isinstance(allowed, list) or any(item not in PERMISSIONS for item in allowed) or len(set(allowed)) != len(allowed):
                raise ValueError('Invalid folder permissions.')
            checked[root] = [item for item in PERMISSIONS if item in allowed]
        names.add(name.casefold())
        result.append({'name': name, 'password': {'salt': password['salt'], 'digest': password['digest']}, 'grants': checked})
    return result


def validate_access_config(config, directory):
    if not config.get('folder_users_enabled'):
        config['folder_users'] = []
        return
    roots = {'/': Path(directory).resolve()}
    roots.update({item['name']: Path(item['path']).resolve() for item in config['shared_folders']})
    config['folder_users'] = validate_users(config.get('folder_users', []), roots)
    if not config['folder_users']:
        raise ValueError('Add at least one folder user before enabling user permissions.')
    # A second URL to an ancestor or descendant could bypass a logical root ACL.
    paths = list(roots.values())
    for index, path in enumerate(paths):
        if any(path.is_relative_to(other) or other.is_relative_to(path) for other in paths[index + 1:]):
            raise ValueError('Folders with user permissions must not overlap. Choose separate root folders.')
    admin = config.get('auth_credentials')
    if admin and any(user['name'].casefold() == admin[0].casefold() for user in config['folder_users']):
        raise ValueError('The general login and folder users must have different names.')


class FolderAccessHTTP:
    def require_permission(self, *permissions):
        allowed = getattr(self, 'folder_permissions', None)
        if allowed is None or all(item in allowed for item in permissions):
            return True
        self.send_error(403, 'Folder permission denied')
        return False

    def authorize_request(self):
        self.folder_permissions = None
        self.folder_user = None
        users = self.config.get('folder_users', [])
        if not users:
            return not self.config.get('auth_credentials') or self.check_auth()
        try:
            kind, token = self.headers.get('Authorization', '').split(' ', 1)
            if kind.lower() != 'basic':
                raise ValueError()
            name, password = base64.b64decode(token, validate=True).decode('utf-8').split(':', 1)
        except (ValueError, UnicodeError):
            self.send_auth_request()
            return False
        admin = self.config.get('auth_credentials')
        if admin and hmac.compare_digest(name.encode(), admin[0].encode()) and hmac.compare_digest(password.encode(), admin[1].encode()):
            return True
        user = next((user for user in users if user['name'] == name), None)
        if user is None or not verify_password(password, user['password']):
            self.send_auth_request()
            return False
        self.folder_user = user
        root = self.url_prefix.rsplit('/', 1)[-1] if self.url_prefix else '/'
        self.folder_permissions = set(user['grants'].get(root, []))
        from urllib.parse import urlsplit, unquote
        route = urlsplit(self.path).path
        if not self.url_prefix and (route.startswith('/_camera') or route == '/api/intent'):
            return self.require_permission('__administrator__')
        if route.startswith('/_serverpy/pwa/'):
            return True  # Generic application assets contain no folder data.
        if self.command == 'DELETE':
            return self.require_permission('delete')
        if self.command == 'PUT' or (self.command == 'POST' and route == '/api/save'):
            if not self.folder_permissions.intersection(('upload', 'edit')):
                return self.require_permission('upload')
            return True  # Existence determines the required permission below.
        if self.command == 'POST':
            required = {'/api/mkdir': ('upload',), '/api/copy': ('download', 'upload'),
                        '/api/move': ('edit', 'delete'), '/api/rename': ('edit', 'delete'),
                        '/api/restore': ('upload',), '/api/undo-move': ('edit', 'delete')}
            return self.require_permission(*required.get(route, ('__administrator__',)))
        if route == '/api/trash':
            return self.require_permission('view', 'delete')
        if route == '/api/moves':
            return self.require_permission('view', 'edit', 'delete')
        if route in ('/api/ping', '/api/search', '/api/folders'):
            return self.require_permission('view')
        if route in ('/api/read', '/api/zip'):
            return self.require_permission('download')
        target = self.safe_resolve_path(unquote(route))
        return self.require_permission('view' if target and os.path.isdir(target) else 'download')
