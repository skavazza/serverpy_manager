"""Android device discovery, file transfer, and USB reverse port forwarding via ADB."""

import hashlib
import os
import posixpath
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


_SERIAL_RE = re.compile(r'^[A-Za-z0-9._:-]{1,128}$')
_PLATFORM_TOOLS_VERSION = '37.0.1'
_PLATFORM_TOOLS = {
    'linux': {
        'url': f'https://dl.google.com/android/repository/platform-tools_r{_PLATFORM_TOOLS_VERSION}-linux.zip',
        'sha256': 'd230f13842f60f782a8645f9c813f8f845bf36089ea7289f28c48f17979313f1',
        'members': ('platform-tools/adb',),
        'executable': 'adb',
    },
    'win32': {
        'url': f'https://dl.google.com/android/repository/platform-tools_r{_PLATFORM_TOOLS_VERSION}-win.zip',
        'sha256': '45f4d63113e895ebde0c90f194099a4676b6ac653bd28d54314a9e022bbc1a99',
        'members': (
            'platform-tools/adb.exe',
            'platform-tools/AdbWinApi.dll',
            'platform-tools/AdbWinUsbApi.dll',
        ),
        'executable': 'adb.exe',
    },
}
_MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024
_MAX_TOOL_SIZE = 50 * 1024 * 1024


def _platform_tools_config():
    if sys.platform == 'win32':
        return _PLATFORM_TOOLS['win32']
    if sys.platform.startswith('linux'):
        if platform.machine().lower() not in ('x86_64', 'amd64'):
            raise OSError('Automatic Android Platform-Tools installation supports Linux x86_64 only.')
        return _PLATFORM_TOOLS['linux']
    raise OSError('Automatic Android Platform-Tools installation supports Windows and Linux only.')


def _platform_tools_directory():
    if sys.platform == 'win32':
        data_root = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
        app_data = data_root / 'ServerPy' / 'HTTPManager'
    elif sys.platform.startswith('linux'):
        data_root = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
        app_data = data_root / 'serverpy-http'
    else:
        raise OSError('Automatic Android Platform-Tools installation supports Windows and Linux only.')
    return app_data / 'android' / f'platform-tools-{_PLATFORM_TOOLS_VERSION}'


def _managed_adb_executable():
    try:
        config = _platform_tools_config()
        executable = _platform_tools_directory() / config['executable']
    except OSError:
        return None
    return str(executable) if executable.is_file() else None


def android_adb_available():
    """Return whether ADB is available on PATH or installed for this user."""
    return bool(shutil.which('adb') or shutil.which('adb.exe') or _managed_adb_executable())


def android_adb_install_supported():
    """Return whether a verified Platform-Tools package is available for this OS."""
    try:
        _platform_tools_config()
    except OSError:
        return False
    return True


def install_android_platform_tools(progress=None):
    """Download and install the pinned Google Platform-Tools package for this user."""
    config = _platform_tools_config()
    destination = _platform_tools_directory()
    if destination.exists():
        raise FileExistsError('The app-managed Android Platform-Tools folder already exists.')
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        dir=destination.parent, prefix='.android-platform-tools-',
    ) as temporary:
        temporary_dir = Path(temporary)
        archive_path = temporary_dir / 'platform-tools.zip'
        digest = hashlib.sha256()
        downloaded = 0
        try:
            with urllib.request.urlopen(config['url'], timeout=30) as response:
                content_length = response.headers.get('Content-Length')
                total = int(content_length) if content_length and content_length.isdigit() else 0
                if total > _MAX_DOWNLOAD_SIZE:
                    raise OSError('Android Platform-Tools download exceeds the size limit.')
                with archive_path.open('wb') as archive:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > _MAX_DOWNLOAD_SIZE:
                            raise OSError('Android Platform-Tools download exceeds the size limit.')
                        digest.update(chunk)
                        archive.write(chunk)
                        if progress:
                            progress(downloaded, total)
        except (OSError, ValueError) as error:
            raise OSError(f'Unable to download Android Platform-Tools: {error}') from error

        if digest.hexdigest() != config['sha256']:
            raise OSError('Android Platform-Tools SHA-256 verification failed.')

        install_dir = temporary_dir / 'platform-tools'
        install_dir.mkdir()
        try:
            with zipfile.ZipFile(archive_path) as archive:
                for member_name in config['members']:
                    matches = [
                        info for info in archive.infolist()
                        if info.filename == member_name
                    ]
                    if len(matches) != 1:
                        raise OSError(f'Invalid Android Platform-Tools archive: missing {member_name}.')
                    info = matches[0]
                    if info.is_dir() or info.file_size > _MAX_TOOL_SIZE:
                        raise OSError(f'Invalid Android Platform-Tools file: {member_name}.')
                    mode = info.external_attr >> 16
                    if mode and (mode & 0o170000) == 0o120000:
                        raise OSError(f'Invalid Android Platform-Tools symbolic link: {member_name}.')
                    output_path = install_dir / Path(member_name).name
                    with archive.open(info) as source, output_path.open('xb') as target:
                        shutil.copyfileobj(source, target)
        except (zipfile.BadZipFile, RuntimeError) as error:
            raise OSError(f'Invalid Android Platform-Tools archive: {error}') from error

        executable = install_dir / config['executable']
        if not executable.is_file():
            raise OSError('The Android Platform-Tools archive does not contain ADB.')
        if sys.platform != 'win32':
            executable.chmod(0o755)
        install_dir.replace(destination)
    return str(destination / config['executable'])


def _adb_executable():
    executable = shutil.which('adb') or shutil.which('adb.exe') or _managed_adb_executable()
    if not executable:
        raise FileNotFoundError(
            'Android Debug Bridge (adb) is not installed or is not available on PATH. '
            'Install Android Platform-Tools from the Android devices panel.'
        )
    return executable


def _validate_serial(serial):
    if not isinstance(serial, str) or not _SERIAL_RE.fullmatch(serial):
        raise ValueError('Select a valid Android device.')


def normalize_android_path(path):
    if not isinstance(path, str) or not path.strip() or any(
        character in path for character in ('\0', '\n', '\r')
    ):
        raise ValueError('Enter a valid absolute Android path.')
    path = path.strip()
    if not path.startswith('/'):
        raise ValueError('Enter a valid absolute Android path.')
    return posixpath.normpath(path)


def _run_adb(arguments, timeout):
    try:
        result = subprocess.run(
            [_adb_executable(), *arguments],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError('ADB operation timed out.') from error
    if result.returncode:
        raise OSError(result.stderr.strip() or result.stdout.strip() or 'ADB operation failed.')
    return result.stdout


def list_android_devices(timeout=10):
    """Return ADB-visible devices, including offline or unauthorized states."""
    output = _run_adb(['devices', '-l'], timeout)
    devices = []
    for line in output.splitlines():
        fields = line.strip().split()
        if len(fields) < 2 or fields[0] == 'List':
            continue
        serial, state = fields[:2]
        _validate_serial(serial)
        details = dict(
            item.split(':', 1) for item in fields[2:] if ':' in item
        )
        devices.append({
            'serial': serial,
            'state': state,
            'model': details.get('model', '').replace('_', ' '),
        })
    return devices


_ENDPOINT_RE = re.compile(
    r'^(?:\d{1,3}(?:\.\d{1,3}){3}|\[[0-9A-Fa-f:]+\]):(\d{1,5})$'
)
_MDNS_SERVICE_RE = re.compile(
    r'^(\S+)\s+(_adb-tls-(?:connect|pairing)\._tcp\.?)\s+(\S+)$'
)


def _validate_endpoint(endpoint):
    if not isinstance(endpoint, str):
        raise ValueError('Enter the phone address as IP:port.')
    endpoint = endpoint.strip()
    match = _ENDPOINT_RE.fullmatch(endpoint)
    if not match or not 1 <= int(match.group(1)) <= 65535:
        raise ValueError('Enter the phone address as IP:port.')
    return endpoint


def discover_android_network_devices(timeout=15):
    """Find phones advertising Wireless debugging on the local network (mDNS)."""
    output = _run_adb(['mdns', 'services'], timeout)
    found = []
    for line in output.splitlines():
        match = _MDNS_SERVICE_RE.fullmatch(line.strip())
        if not match:
            continue
        name, service, endpoint = match.groups()
        try:
            endpoint = _validate_endpoint(endpoint)
        except ValueError:
            continue
        found.append({
            'name': name,
            'endpoint': endpoint,
            'pairing': 'pairing' in service,
        })
    return found


def pair_android_device(endpoint, code, timeout=30):
    """Pair with a phone using the six-digit code shown by Wireless debugging."""
    endpoint = _validate_endpoint(endpoint)
    if not isinstance(code, str) or not re.fullmatch(r'\d{6}', code.strip()):
        raise ValueError('Enter the six-digit pairing code.')
    output = _run_adb(['pair', endpoint, code.strip()], timeout).strip()
    if 'successfully paired' not in output.lower():
        raise OSError(output or 'Android pairing failed.')
    return output


def connect_android_device(endpoint, timeout=20):
    """Connect to a paired phone over the network."""
    endpoint = _validate_endpoint(endpoint)
    output = _run_adb(['connect', endpoint], timeout).strip()
    if not output.lower().startswith(('connected to', 'already connected to')):
        raise OSError(output or 'Android network connection failed.')
    return output


def disconnect_android_device(endpoint, timeout=10):
    """Drop a network ADB connection."""
    endpoint = _validate_endpoint(endpoint)
    return _run_adb(['disconnect', endpoint], timeout).strip()


def list_android_directory(serial, remote_path, timeout=10):
    """List one directory using Android's ls output; directories have a trailing slash."""
    _validate_serial(serial)
    path = normalize_android_path(remote_path)
    command = f'ls -1Ap -- {shlex.quote(path)}'
    output = _run_adb(['-s', serial, 'shell', command], timeout)
    entries = []
    for line in output.splitlines():
        name = line.rstrip('/')
        if not name or name in ('.', '..'):
            continue
        entries.append({'name': name, 'is_dir': line.endswith('/')})
    return entries


def transfer_android_file(serial, direction, local_path, remote_path, timeout=3600):
    """Transfer a file with adb pull/push without invoking a shell for host paths."""
    _validate_serial(serial)
    if direction not in ('pull', 'push'):
        raise ValueError('Choose a valid Android transfer direction.')
    if not isinstance(local_path, str) or not local_path.strip():
        raise ValueError('Select a local file.')
    remote_path = normalize_android_path(remote_path)
    if direction == 'pull':
        arguments = ['-s', serial, 'pull', remote_path, local_path]
    else:
        arguments = ['-s', serial, 'push', local_path, remote_path]
    return _run_adb(arguments, timeout).strip()


def install_android_apk(serial, local_path, timeout=3600):
    """Install one user-selected APK with ADB; do not replace an existing package."""
    _validate_serial(serial)
    if not isinstance(local_path, str) or not local_path.strip():
        raise ValueError('Select an APK file.')
    apk_path = Path(local_path)
    if apk_path.suffix.lower() != '.apk' or not apk_path.is_file():
        raise ValueError('Select an existing APK file.')
    return _run_adb(['-s', serial, 'install', str(apk_path)], timeout).strip()


def capture_android_screenshot(serial, local_path, overwrite=False, timeout=20):
    """Capture a PNG through ADB and atomically save it to a local file."""
    _validate_serial(serial)
    if not isinstance(local_path, str) or not local_path.strip():
        raise ValueError('Choose a local PNG file path.')
    destination = Path(local_path)
    if destination.suffix.lower() != '.png':
        raise ValueError('Choose a PNG image file.')
    if destination.exists() and not overwrite:
        raise FileExistsError('The selected screenshot file already exists.')
    if not destination.parent.is_dir():
        raise ValueError('Choose an existing local folder for the screenshot.')
    try:
        result = subprocess.run(
            [_adb_executable(), '-s', serial, 'exec-out', 'screencap', '-p'],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError('Android screenshot capture timed out.') from error
    if result.returncode:
        message = result.stderr.decode('utf-8', errors='replace').strip()
        raise OSError(message or 'Android screenshot capture failed.')
    image = result.stdout
    if not image.startswith(b'\x89PNG\r\n\x1a\n') or len(image) > 64 * 1024 * 1024:
        raise OSError('Android did not return a valid PNG screenshot.')

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='wb', dir=destination.parent, prefix='.android-screenshot-',
            suffix='.tmp', delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(image)
        if destination.exists() and not overwrite:
            raise FileExistsError('The selected screenshot file already exists.')
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return str(destination)


def send_android_control(serial, action, timeout=10):
    """Send one allowlisted navigation, power, volume, or system-panel action."""
    _validate_serial(serial)
    key_events = {
        'back': '4',
        'home': '3',
        'recent_apps': '187',
        'power': '26',
        'screen_off': '223',
        'screen_on': '224',
        'volume_up': '24',
        'volume_down': '25',
    }
    shell_commands = {
        'notifications': ['cmd', 'statusbar', 'expand-notifications'],
        'quick_settings': ['cmd', 'statusbar', 'expand-settings'],
        'collapse_panels': ['cmd', 'statusbar', 'collapse'],
    }
    if action in key_events:
        arguments = ['-s', serial, 'shell', 'input', 'keyevent', key_events[action]]
        return _run_adb(arguments, timeout).strip()
    if action in shell_commands:
        return _run_adb(['-s', serial, 'shell', *shell_commands[action]], timeout).strip()
    if action == 'rotate':
        output = _run_adb(
            ['-s', serial, 'shell', 'settings', 'get', 'system', 'user_rotation'],
            timeout,
        ).strip()
        if output not in ('0', '1', '2', '3'):
            raise OSError('Unable to read the Android screen rotation setting.')
        _run_adb(
            ['-s', serial, 'shell', 'settings', 'put', 'system', 'accelerometer_rotation', '0'],
            timeout,
        )
        next_rotation = str((int(output) + 1) % 4)
        return _run_adb(
            ['-s', serial, 'shell', 'settings', 'put', 'system', 'user_rotation', next_rotation],
            timeout,
        ).strip()
    if action == 'auto_rotation':
        return _run_adb(
            ['-s', serial, 'shell', 'settings', 'put', 'system', 'accelerometer_rotation', '1'],
            timeout,
        ).strip()
    raise ValueError('Choose a supported Android control action.')


def set_android_reverse(serial, port, enabled, timeout=10):
    """Create or remove an authorized device's localhost TCP reverse mapping."""
    _validate_serial(serial)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('Choose a valid HTTP server port.')
    mapping = f'tcp:{port}'
    arguments = ['-s', serial, 'reverse']
    arguments.extend(['--remove', mapping] if not enabled else [mapping, mapping])
    return _run_adb(arguments, timeout).strip()
