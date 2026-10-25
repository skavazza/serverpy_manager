"""Linux administrator elevation by relaunching the app through polkit (pkexec)."""

import os
from pathlib import Path
import signal
import subprocess
import sys

PKEXEC = '/usr/bin/pkexec'
ENV = '/usr/bin/env'
REPLACE_VARIABLE = 'SERVERPY_REPLACE_PID'
# Variables a root Qt process needs to reach the user's display session.
PASSTHROUGH = ('DISPLAY', 'XAUTHORITY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR', 'QT_QPA_PLATFORM', 'LANG')


def needs_elevation():
    return sys.platform.startswith('linux') and os.geteuid() != 0


def elevation_available():
    return needs_elevation() and os.access(PKEXEC, os.X_OK)


def elevated_command(environ=None):
    environ = os.environ if environ is None else environ
    project = Path(__file__).resolve().parents[2]
    values = [f'{name}={environ[name]}' for name in PASSTHROUGH if environ.get(name)]
    values.append(f'PYTHONPATH={project}')
    values.append(f'{REPLACE_VARIABLE}={os.getpid()}')
    return [PKEXEC, ENV, *values, sys.executable, str(project / 'src' / 'main.py')]


def relaunch_elevated():
    """Start an administrator copy of the app and return its pkexec process."""
    if not elevation_available():
        return None
    return subprocess.Popen(elevated_command(), cwd=Path(__file__).resolve().parents[2],
                            start_new_session=True)


def release_replaced_instance():
    """Called by the administrator copy once its window is visible: close the user copy."""
    if not sys.platform.startswith('linux'):
        return
    value = os.environ.pop(REPLACE_VARIABLE, '')
    if os.geteuid() != 0 or not value.isdigit() or not os.environ.get('PKEXEC_UID', '').isdigit():
        return
    pid = int(value)
    try:
        owner = os.stat(f'/proc/{pid}').st_uid
        command = Path(f'/proc/{pid}/cmdline').read_bytes()
        if owner == int(os.environ['PKEXEC_UID']) and b'src/main.py' in command:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
