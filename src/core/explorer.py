"""Persistent, reversible file operations and bounded folder search."""

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path


STATE_FOLDER = '.serverpy'


class ExplorerError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class FileExplorer:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.state_dir = self.root / STATE_FOLDER
        self.lock = threading.RLock()

    def resolve(self, relative, allow_root=False):
        if not isinstance(relative, str):
            raise ExplorerError(400, 'Invalid path')
        path = Path(os.path.abspath(self.root / relative.lstrip('/\\')))
        resolved = path.resolve()
        if not path.is_relative_to(self.root) or not resolved.is_relative_to(self.root) or path.is_relative_to(self.state_dir) or resolved.is_relative_to(self.state_dir):
            raise ExplorerError(403, 'Access denied')
        if not allow_root and path == self.root:
            raise ExplorerError(403, 'Access denied')
        return path

    def relative(self, path):
        return '/' + Path(path).relative_to(self.root).as_posix()

    def _read(self):
        if self.state_dir.is_symlink() or self.state_dir.resolve() != self.state_dir:
            raise ExplorerError(403, 'Access denied')
        manifest = self.state_dir / 'manifest.json'
        if not manifest.exists():
            return {'trash': [], 'moves': []}
        try:
            with manifest.open(encoding='utf-8') as file:
                state = json.load(file)
        except (ValueError, UnicodeError):
            raise ExplorerError(500, 'Invalid recovery data')
        if not isinstance(state, dict) or not isinstance(state.get('trash'), list) or not isinstance(state.get('moves'), list):
            raise ExplorerError(500, 'Invalid recovery data')
        for kind, required in (('trash', ('id', 'name', 'path', 'directory', 'deleted')), ('moves', ('id', 'name', 'source', 'destination', 'moved', 'signature'))):
            for item in state[kind]:
                if not isinstance(item, dict) or any(key not in item for key in required) or not isinstance(item['id'], str) or len(item['id']) != 32 or any(char not in '0123456789abcdef' for char in item['id']):
                    raise ExplorerError(500, 'Invalid recovery data')
        return state

    def _write(self, state):
        self.state_dir.mkdir(exist_ok=True)
        temporary = self.state_dir / (uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, self.state_dir / 'manifest.json')
        finally:
            temporary.unlink(missing_ok=True)

    def list_trash(self):
        with self.lock:
            return sorted(self._read()['trash'], key=lambda item: item['deleted'], reverse=True)

    def trash(self, relative):
        with self.lock:
            source = self.resolve(relative)
            if not os.path.lexists(source):
                raise ExplorerError(404, 'Source not found')
            state = self._read()
            item = {'id': uuid.uuid4().hex, 'name': source.name, 'path': self.relative(source), 'directory': source.is_dir(), 'deleted': time.time()}
            payload_dir = self.state_dir / 'trash'
            if payload_dir.resolve() != payload_dir:
                raise ExplorerError(403, 'Access denied')
            payload_dir.mkdir(parents=True, exist_ok=True)
            destination = payload_dir / item['id']
            shutil.move(str(source), str(destination))
            try:
                state['trash'].append(item)
                self._write(state)
            except Exception:
                shutil.move(str(destination), str(source))
                raise
            return item

    def restore(self, item_id):
        with self.lock:
            state = self._read()
            item = next((item for item in state['trash'] if item['id'] == item_id), None)
            if not item:
                raise ExplorerError(404, 'Recovery item not found')
            destination = self.resolve(item['path'])
            source = self.state_dir / 'trash' / item['id']
            if not source.parent.resolve().is_relative_to(self.state_dir):
                raise ExplorerError(403, 'Access denied')
            if not os.path.lexists(source):
                raise ExplorerError(404, 'Recovery item not found')
            if os.path.lexists(destination):
                raise ExplorerError(409, 'Destination already exists')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            try:
                state['trash'].remove(item)
                self._write(state)
            except Exception:
                shutil.move(str(destination), str(source))
                raise
            return item

    @staticmethod
    def signature(path):
        stat = path.lstat()
        return [stat.st_ino, stat.st_size, stat.st_mtime_ns]

    def move(self, source_path, destination_path):
        with self.lock:
            source, destination = self.resolve(source_path), self.resolve(destination_path)
            if not os.path.lexists(source):
                raise ExplorerError(404, 'Source not found')
            if os.path.lexists(destination):
                raise ExplorerError(409, 'Destination already exists')
            if destination.is_relative_to(source):
                raise ExplorerError(409, 'Cannot move a folder into itself')
            state = self._read()
            shutil.move(str(source), str(destination))
            try:
                item = {'id': uuid.uuid4().hex, 'name': destination.name, 'source': self.relative(source), 'destination': self.relative(destination), 'moved': time.time(), 'signature': self.signature(destination)}
                state['moves'] = (state['moves'] + [item])[-50:]
                self._write(state)
            except Exception:
                shutil.move(str(destination), str(source))
                raise
            return item

    def list_moves(self):
        with self.lock:
            return list(reversed(self._read()['moves']))

    def undo_move(self, item_id):
        with self.lock:
            state = self._read()
            item = next((item for item in state['moves'] if item['id'] == item_id), None)
            if not item:
                raise ExplorerError(404, 'Recovery item not found')
            source, destination = self.resolve(item['destination']), self.resolve(item['source'])
            if not os.path.lexists(source):
                raise ExplorerError(404, 'Source not found')
            if os.path.lexists(destination):
                raise ExplorerError(409, 'Destination already exists')
            if self.signature(source) != item['signature']:
                raise ExplorerError(409, 'Moved item has changed')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            try:
                state['moves'].remove(item)
                self._write(state)
            except Exception:
                shutil.move(str(destination), str(source))
                raise
            return item

    def search(self, query, relative='/', limit=500, max_entries=10000):
        start = self.resolve(relative, allow_root=True)
        if not start.is_dir():
            raise ExplorerError(404, 'Directory not found')
        query = query.strip().casefold()
        if not query or len(query) > 200:
            raise ExplorerError(400, 'Enter a search term')
        results, scanned, partial = [], 0, False
        for directory, folders, files in os.walk(start, followlinks=False):
            folders[:] = [name for name in folders if name.casefold() != STATE_FOLDER and not (Path(directory) / name).is_symlink() and not getattr(Path(directory) / name, 'is_junction', lambda: False)() and (Path(directory) / name).resolve().is_relative_to(self.root) and not (Path(directory) / name).resolve().is_relative_to(self.state_dir)]
            for name in sorted(folders + files, key=str.casefold):
                scanned += 1
                if scanned > max_entries:
                    partial = True
                    break
                if name.casefold() == STATE_FOLDER or query not in name.casefold():
                    continue
                path = Path(directory) / name
                try:
                    self.resolve(self.relative(path))
                    stat = path.stat()
                except (OSError, ExplorerError):
                    continue
                results.append({'name': name, 'path': self.relative(path), 'directory': path.is_dir(), 'size': 0 if path.is_dir() else stat.st_size, 'modified': stat.st_mtime})
                if len(results) >= limit:
                    partial = True
                    break
            if partial:
                break
        return {'items': results, 'partial': partial}
