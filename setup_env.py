"""Shared dependency check/repair for both launchers; standard library only."""

import importlib
from importlib import metadata
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
MODULES = ('PySide6.QtCore', 'PySide6.QtWidgets', 'PySide6.QtUiTools',
           'PySide6.QtMultimedia', 'psutil', 'qrcode', 'paramiko')


def pinned_versions():
    pinned = {}
    for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith(('#', '-c ')):
            continue
        name, version = line.split('==', 1)
        pinned[name] = version
    return pinned


def check_environment():
    # Constraints pin dependency resolution; optional platform packages are
    # installed by pip only when required by the selected distribution.
    problems = []
    for name, expected in pinned_versions().items():
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            problems.append('Missing dependency: ' + name)
            continue
        if actual != expected:
            problems.append(f'{name}: expected {expected}, found {actual}')
    if not problems:
        for module in MODULES:
            try:
                importlib.import_module(module)
            except Exception as error:
                problems.append(f'Unable to import {module}: {error}')
    return problems


def main():
    if sys.version_info < (3, 10):
        print('Python 3.10 or newer is required.', file=sys.stderr)
        return 1
    problems = check_environment()
    if not problems:
        return 0
    print('\n'.join(problems))
    if '--check' in sys.argv:
        return 1
    print('Installing the pinned project dependencies...')
    result = subprocess.run([sys.executable, '-m', 'pip', 'install', '-r',
                             str(ROOT / 'requirements.txt')], cwd=ROOT)
    if result.returncode:
        print('Dependency installation failed. The application was not started.', file=sys.stderr)
        return result.returncode
    # Imports already loaded in this process can be stale after pip changes.
    return subprocess.run([sys.executable, str(Path(__file__).resolve()), '--check'], cwd=ROOT).returncode


if __name__ == '__main__':
    raise SystemExit(main())
