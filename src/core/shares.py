"""Validate named HTTP roots independently of URL routing."""

import os
import re


SHARES_PREFIX = '/_shares/'


def validate_shared_folders(items, check_paths=True):
    if not isinstance(items, list) or len(items) > 32:
        raise ValueError('Configure at most 32 additional folders.')
    result, names = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Invalid shared folder configuration.')
        name, path = item.get('name'), item.get('path')
        if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}', name):
            raise ValueError('Use 1 to 40 letters, numbers, hyphens or underscores for the folder name.')
        if name.casefold() in names:
            raise ValueError('Each shared folder must have a unique name.')
        if not isinstance(path, str) or not os.path.isabs(path):
            raise ValueError('Select an existing folder.')
        if check_paths and (not os.path.isdir(path) or not os.access(path, os.R_OK | os.X_OK)):
            raise ValueError('A shared folder is unavailable: ' + name)
        if not isinstance(item.get('writable', False), bool):
            raise ValueError('Invalid shared folder configuration.')
        names.add(name.casefold())
        result.append({'name': name, 'path': os.path.abspath(path), 'writable': item.get('writable', False)})
    return result
