"""Translate server controls into an isolated runtime configuration snapshot."""

from copy import deepcopy
import ipaddress
import re


def normalize_public_hostname(value):
    try:
        hostname = value.strip().rstrip('.').encode('idna').decode('ascii').lower()
    except UnicodeError:
        return ''
    labels = hostname.split('.')
    valid = (
        len(hostname) <= 253
        and len(labels) >= 2
        and any(character.isalpha() for character in labels[-1])
        and all(
            1 <= len(label) <= 63
            and re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', label)
            for label in labels
        )
    )
    return hostname if valid else ''


class ServerConfigurationError(ValueError):
    """A translatable configuration message for the controller to present."""


def build_server_config(controller):
    window = controller.window
    config = {
        'use_tls': window.chk_tls.isChecked(),
        'cert_file': controller.cert_path,
        'render_pages': window.chk_render_pages.isChecked(),
        'allow_mod': window.chk_allow_mod.isChecked(),
        'enable_intents': window.chk_intent.isChecked(),
        'verify_host': window.chk_verify_header.isChecked(),
        'cloudflare_tunnel': window.chk_cloudflare_tunnel.isChecked(),
        'cloudflare_hostname': normalize_public_hostname(window.line_cloudflare_hostname.text()),
        'cors_config': deepcopy(controller.cors_config),
        'custom_headers': dict(controller.custom_headers) if window.chk_custom_headers.isChecked() else {},
        'redirections': deepcopy(controller.redirections),
        'shared_folders': deepcopy(controller.shared_folders),
        'folder_users': deepcopy(controller.folder_users),
        'folder_users_enabled': controller.folder_users_enabled,
    }
    if window.chk_auth.isChecked():
        user, password = window.line_username.text(), window.line_password.text()
        if not user or not password:
            raise ServerConfigurationError('Error: Username and password required for auth.')
        config['auth_credentials'] = (user, password)
    if config['enable_intents'] and not config.get('auth_credentials'):
        raise ServerConfigurationError('System intents require a general administrator login and password.')
    if window.chk_whitelist.isChecked():
        try:
            config['whitelist'] = [str(ipaddress.ip_address(value.strip()))
                                   for value in window.line_whitelist.text().split(',') if value.strip()]
        except ValueError:
            raise ServerConfigurationError('Enter valid IP addresses separated by commas.') from None
    if window.chk_rate_limit.isChecked():
        try:
            config['rate_limit'] = int(window.line_rate_limit.text())
        except ValueError:
            raise ServerConfigurationError('Error: Invalid rate limit.') from None
    if window.chk_custom_charset.isChecked():
        config['custom_charset'] = window.line_custom_charset.text().strip()
    return config
