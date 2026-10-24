"""Build bounded archives on disk, without buffering the archive in RAM."""

import os
from pathlib import Path
import time
import zipfile

from .explorer import STATE_FOLDER, ExplorerError
from .http_limits import HTTPResourceError


class LimitedArchive:
    def __init__(self, stream, limit):
        self.stream, self.limit = stream, limit

    def write(self, data):
        if self.stream.tell() + len(data) > self.limit:
            raise HTTPResourceError(413, 'ZIP exceeds the configured size limit')
        return self.stream.write(data)

    def __getattr__(self, name):
        return getattr(self.stream, name)


def build_archive(explorer, folder, destination, config):
    deadline = time.monotonic() + config['zip_timeout']
    total = entries = 0

    def check_time():
        if time.monotonic() >= deadline:
            raise HTTPResourceError(503, 'ZIP generation timed out')

    with zipfile.ZipFile(LimitedArchive(destination, config['zip_max_bytes']), 'w', zipfile.ZIP_DEFLATED) as archive:
        for root, dirs, files in os.walk(folder, followlinks=False):
            check_time()
            # Bound traversal as well as file metadata retained by ZipFile.
            entries += len(dirs) + len(files)
            if entries > config['zip_max_entries']:
                raise HTTPResourceError(413, 'ZIP contains too many entries')
            safe_dirs = []
            for name in dirs:
                path = Path(root) / name
                if name.casefold() == STATE_FOLDER or path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                    continue
                try:
                    explorer.resolve(explorer.relative(path))
                    safe_dirs.append(name)
                except ExplorerError:
                    pass
            dirs[:] = safe_dirs
            for name in files:
                check_time()
                source = Path(root) / name
                if source.is_symlink():
                    continue
                try:
                    source = explorer.resolve(explorer.relative(source))
                except ExplorerError:
                    continue
                if not source.is_file():
                    continue
                if total + source.stat().st_size > config['zip_max_bytes']:
                    raise HTTPResourceError(413, 'ZIP source exceeds the configured size limit')
                relative = os.path.relpath(source, folder)
                with source.open('rb') as incoming, archive.open(relative, 'w', force_zip64=True) as outgoing:
                    while True:
                        check_time()
                        chunk = incoming.read(64 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > config['zip_max_bytes']:
                            raise HTTPResourceError(413, 'ZIP source exceeds the configured size limit')
                        outgoing.write(chunk)
    destination.flush()
    destination.seek(0, os.SEEK_END)
    size = destination.tell()
    destination.seek(0)
    return size
