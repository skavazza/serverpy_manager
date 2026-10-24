"""Stage uploads in reserved storage; publish only complete files atomically."""

import os
from pathlib import Path
import tempfile

from .explorer import ExplorerError


class StagedUpload:
    def __init__(self, explorer, relative, exclusive):
        with explorer.lock:
            self._prepare(explorer, relative, exclusive)

    def _prepare(self, explorer, relative, exclusive):
        self.explorer, self.relative, self.exclusive = explorer, relative, exclusive
        self.path = explorer.resolve(relative)
        if exclusive and os.path.lexists(self.path):
            raise ExplorerError(412, 'A file with this name already exists')
        state = explorer.state_dir
        payload = state / 'uploads'
        if state.resolve() != state or payload.resolve() != payload:
            raise ExplorerError(403, 'Access denied')
        state.mkdir(exist_ok=True)
        payload.mkdir(exist_ok=True)
        descriptor, name = tempfile.mkstemp(suffix='.part', dir=payload)
        self.temporary = Path(name)
        try:
            self.stream = os.fdopen(descriptor, 'wb')
        except Exception:
            os.close(descriptor)
            self.temporary.unlink(missing_ok=True)
            raise

    def __enter__(self):
        return self

    def commit(self):
        self.stream.close()
        with self.explorer.lock:
            path = self.explorer.resolve(self.relative)
            if path != self.path:
                raise ExplorerError(409, 'Destination changed')
            path.parent.mkdir(parents=True, exist_ok=True)
            if self.exclusive:
                try:
                    if os.name == 'nt':
                        # Windows rename does not overwrite an existing target.
                        os.rename(self.temporary, path)
                    else:
                        os.link(self.temporary, path)
                        self.temporary.unlink()
                except FileExistsError:
                    raise ExplorerError(412, 'A file with this name already exists') from None
            else:
                os.replace(self.temporary, path)

    def __exit__(self, *args):
        try:
            self.stream.close()
        finally:
            self.temporary.unlink(missing_ok=True)
