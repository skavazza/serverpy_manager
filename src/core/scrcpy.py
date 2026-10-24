"""Download and validate official scrcpy releases for the current user."""

import hashlib
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
import zlib
from pathlib import Path, PurePosixPath


_SCRCPY_VERSION = '5.0.1'
_RELEASE_URL = f'https://github.com/Genymobile/scrcpy/releases/download/v{_SCRCPY_VERSION}'
_RELEASES = {
    ('win32', 'amd64'): {
        'filename': f'scrcpy-win64-v{_SCRCPY_VERSION}.zip',
        'sha256': 'b12a2c4ee8be317422451fc7dcf8ee20a71b5ea7ef9ad73ddd825a25316227a5',
        'archive': 'zip',
        'executable': 'scrcpy.exe',
    },
    ('win32', 'arm64'): {
        'filename': f'scrcpy-winarm64-v{_SCRCPY_VERSION}.zip',
        'sha256': '16c3fc2068df64946f670e3504b4752073ebae47a416a45b46e79a5ab19c689b',
        'archive': 'zip',
        'executable': 'scrcpy.exe',
    },
    ('linux', 'x86_64'): {
        'filename': f'scrcpy-linux-x86_64-v{_SCRCPY_VERSION}.tar.gz',
        'sha256': '9f969d30cc574816077edecda65719c1c70b0aee1df1ba5fa00779ac07b8fd6e',
        'archive': 'tar.gz',
        'executable': 'scrcpy',
    },
}
_MAX_DOWNLOAD_SIZE = 150 * 1024 * 1024
_MAX_EXTRACTED_SIZE = 500 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 3000


def _release_config():
    os_name = 'win32' if sys.platform == 'win32' else 'linux' if sys.platform.startswith('linux') else None
    machine = platform.machine().lower()
    if os_name == 'win32':
        architecture = {
            'x86_64': 'amd64',
            'amd64': 'amd64',
            'aarch64': 'arm64',
            'arm64': 'arm64',
        }.get(machine, machine)
    elif os_name == 'linux':
        architecture = {
            'x86_64': 'x86_64',
            'amd64': 'x86_64',
        }.get(machine, machine)
    else:
        architecture = machine
    config = _RELEASES.get((os_name, architecture))
    if config is None:
        raise OSError(
            'Automatic scrcpy installation supports Windows x86_64/ARM64 '
            'and Linux x86_64 only.'
        )
    return config


def _scrcpy_directory():
    if sys.platform == 'win32':
        data_root = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
        app_data = data_root / 'ServerPy' / 'HTTPManager'
    elif sys.platform.startswith('linux'):
        data_root = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
        app_data = data_root / 'serverpy-http'
    else:
        raise OSError('Automatic scrcpy installation supports Windows and Linux only.')
    return app_data / 'android' / f'scrcpy-{_SCRCPY_VERSION}'


def scrcpy_download_supported():
    """Return whether this OS and architecture have a pinned official release."""
    try:
        _release_config()
    except OSError:
        return False
    return True


def scrcpy_executable():
    """Return the system or app-managed scrcpy executable, if available."""
    executable_name = 'scrcpy.exe' if sys.platform == 'win32' else 'scrcpy'
    system_executable = shutil.which(executable_name)
    if system_executable:
        return system_executable
    try:
        config = _release_config()
        executable = _scrcpy_directory() / config['executable']
    except OSError:
        return None
    if not executable.is_file():
        return None
    _repair_managed_executables(executable.parent, config)
    return str(executable)


def _ensure_executable(path):
    if sys.platform == 'win32':
        return
    try:
        path.chmod(path.stat().st_mode | 0o111)
    except OSError as error:
        raise OSError(f'Unable to set executable permissions on {path.name}: {error}') from error


def _repair_managed_executables(directory, config):
    if sys.platform == 'win32':
        return
    for name in (config['executable'], 'adb'):
        path = directory / name
        if path.is_file():
            _ensure_executable(path)


def scrcpy_available():
    return scrcpy_executable() is not None


def _safe_member_path(name, expected_root):
    if not isinstance(name, str) or not name or '\0' in name or '\\' in name:
        raise OSError('Invalid path in scrcpy archive.')
    path_components = name.rstrip('/').split('/')
    if any(part in ('', '.', '..') or ':' in part for part in path_components):
        raise OSError('Unsafe path in scrcpy archive.')
    path = PurePosixPath(name)
    if path.is_absolute():
        raise OSError('Unsafe path in scrcpy archive.')
    if not path.parts or path.parts[0] != expected_root:
        raise OSError('Unexpected directory in scrcpy archive.')
    return path


def _extract_zip(archive_path, destination, expected_root):
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > _MAX_ARCHIVE_MEMBERS:
            raise OSError('scrcpy archive contains too many files.')
        extracted_size = 0
        for info in members:
            member_path = _safe_member_path(info.filename, expected_root)
            mode = info.external_attr >> 16
            file_type = mode & 0o170000
            is_directory = info.is_dir()
            if file_type == 0o120000 or file_type not in (0, 0o100000, 0o040000):
                raise OSError('scrcpy archive contains an unsupported file type.')
            if file_type == 0o040000 and not is_directory:
                raise OSError('scrcpy archive contains an invalid directory entry.')
            if is_directory:
                (destination / Path(*member_path.parts)).mkdir(parents=True, exist_ok=True)
                continue
            extracted_size += info.file_size
            if extracted_size > _MAX_EXTRACTED_SIZE:
                raise OSError('scrcpy archive exceeds the extraction size limit.')
            output_path = destination / Path(*member_path.parts)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, output_path.open('xb') as target:
                shutil.copyfileobj(source, target)
            if mode & 0o111:
                output_path.chmod(mode & 0o777)


def _extract_tar(archive_path, destination, expected_root):
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        if len(members) > _MAX_ARCHIVE_MEMBERS:
            raise OSError('scrcpy archive contains too many files.')
        extracted_size = 0
        for member in members:
            member_path = _safe_member_path(member.name, expected_root)
            if member.isdir():
                (destination / Path(*member_path.parts)).mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise OSError('scrcpy archive contains an unsupported file type.')
            extracted_size += member.size
            if extracted_size > _MAX_EXTRACTED_SIZE:
                raise OSError('scrcpy archive exceeds the extraction size limit.')
            source = archive.extractfile(member)
            if source is None:
                raise OSError(f'Unable to read scrcpy archive file: {member.name}')
            output_path = destination / Path(*member_path.parts)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with source, output_path.open('xb') as target:
                shutil.copyfileobj(source, target)
            output_path.chmod(member.mode & 0o777)


def install_scrcpy(progress=None):
    """Download a pinned official scrcpy build, verify its hash, and install it."""
    config = _release_config()
    destination = _scrcpy_directory()
    if destination.is_dir():
        executable = destination / config['executable']
        if executable.is_file():
            _repair_managed_executables(destination, config)
            return str(executable)
        raise FileExistsError('The app-managed scrcpy folder exists but is incomplete.')
    if destination.exists():
        raise FileExistsError('The app-managed scrcpy destination is not a directory.')
    destination.parent.mkdir(parents=True, exist_ok=True)

    filename = config['filename']
    expected_root = filename.removesuffix('.tar.gz').removesuffix('.zip')
    url = f'{_RELEASE_URL}/{filename}'
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.scrcpy-install-') as temporary:
        temporary_dir = Path(temporary)
        archive_path = temporary_dir / filename
        digest = hashlib.sha256()
        downloaded = 0
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                content_length = response.headers.get('Content-Length')
                total = int(content_length) if content_length and content_length.isdigit() else 0
                if total > _MAX_DOWNLOAD_SIZE:
                    raise OSError('scrcpy download exceeds the size limit.')
                with archive_path.open('wb') as archive_file:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > _MAX_DOWNLOAD_SIZE:
                            raise OSError('scrcpy download exceeds the size limit.')
                        digest.update(chunk)
                        archive_file.write(chunk)
                        if progress:
                            progress(downloaded, total)
        except (OSError, ValueError) as error:
            raise OSError(f'Unable to download scrcpy: {error}') from error

        if digest.hexdigest() != config['sha256']:
            raise OSError('scrcpy SHA-256 verification failed.')

        extracted = temporary_dir / 'extracted'
        extracted.mkdir()
        try:
            if config['archive'] == 'zip':
                _extract_zip(archive_path, extracted, expected_root)
            else:
                _extract_tar(archive_path, extracted, expected_root)
        except (tarfile.TarError, zipfile.BadZipFile, EOFError, RuntimeError, zlib.error) as error:
            raise OSError(f'Invalid scrcpy archive: {error}') from error

        install_dir = extracted / expected_root
        executable = install_dir / config['executable']
        if not executable.is_file():
            raise OSError('The scrcpy release archive does not contain its executable.')
        _repair_managed_executables(install_dir, config)
        if not (install_dir / 'scrcpy-server').is_file():
            raise OSError('The scrcpy release archive does not contain scrcpy-server.')
        install_dir.replace(destination)
    return str(destination / config['executable'])
