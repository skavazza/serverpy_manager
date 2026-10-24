"""File mutation routes, dispatched after HTTP authentication and root selection."""

import os
import shutil

from .explorer import ExplorerError
from .http_limits import HTTPResourceError

FILE_POST_ROUTES = frozenset((
    '/api/restore', '/api/undo-move', '/api/mkdir', '/api/rename',
    '/api/copy', '/api/move', '/api/save',
))


class FileOperationsHTTP:
    def handle_file_post(self):
        config = self.config
        if self.path in ('/api/restore', '/api/undo-move'):
            if not config.get('allow_mod'):
                self.send_error(405, 'Modification not allowed')
                return
            try:
                data = self.read_json_body()
                if not isinstance(data, dict) or not isinstance(data.get('id'), str):
                    self.send_error(400, 'Invalid recovery item')
                    return
                action = self.explorer.restore if self.path == '/api/restore' else self.explorer.undo_move
                self.send_json(action(data['id']))
            except ExplorerError as error:
                self.send_error(error.status, str(error))
            except (ValueError, TypeError):
                self.send_error(400, 'Invalid recovery item')
            except OSError:
                self.send_error(500, 'Unable to recover item')
            return

        # File management APIs
        if self.path in ['/api/mkdir', '/api/rename', '/api/copy', '/api/move', '/api/save']:
            if not config.get('allow_mod'):
                self.send_error(405, "Modification not allowed")
                return

            try:
                data = self.read_json_body()

                if self.path == '/api/save':
                    file_path = self.safe_resolve_path(data.get('path', ''))
                    if not file_path:
                        self.send_error(403, "Access denied: Invalid path")
                        return
                    if not self.require_permission('edit' if os.path.lexists(file_path) else 'upload'): return
                    mode = 'x' if self.folder_permissions is not None and 'edit' not in self.folder_permissions else 'w'
                    with open(file_path, mode, encoding='utf-8') as f:
                        f.write(data.get('content', ''))
                    self.send_response(200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

                elif self.path == '/api/mkdir':
                    target_dir = self.safe_resolve_path(data.get('path', ''))
                    if not target_dir:
                        self.send_error(403, "Access denied: Invalid path")
                        return
                    if os.path.exists(target_dir):
                        self.send_error(409, "Destination already exists")
                        return
                    os.makedirs(target_dir, exist_ok=True)
                    self.send_response(201)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

                elif self.path in ('/api/rename', '/api/move'):
                    src = self.safe_resolve_path(data.get('src') or data.get('old', ''))
                    dst = self.safe_resolve_path(data.get('dst') or data.get('new', ''))
                    if not src or not dst:
                        self.send_error(403, "Access denied: Invalid path")
                        return
                    if not os.path.exists(src):
                        self.send_error(404, "Source not found")
                        return
                    if os.path.exists(dst):
                        self.send_error(409, "Destination already exists")
                        return
                    if os.path.isdir(src) and dst.startswith(src + os.sep):
                        self.send_error(409, "Cannot move a folder into itself")
                        return
                    self.explorer.move(data.get('src') or data.get('old', ''), data.get('dst') or data.get('new', ''))
                    self.send_response(200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

                elif self.path == '/api/copy':
                    src = self.safe_resolve_path(data.get('src', ''))
                    dst = self.safe_resolve_path(data.get('dst', ''))
                    if not src or not dst:
                        self.send_error(403, "Access denied: Invalid path")
                        return
                    if not os.path.exists(src):
                        self.send_error(404, "Source not found")
                        return
                    if os.path.exists(dst):
                        self.send_error(409, "Destination already exists")
                        return
                    if os.path.isdir(src) and dst.startswith(src + os.sep):
                        self.send_error(409, "Cannot copy a folder into itself")
                        return
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
                    self.send_response(200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            except HTTPResourceError:
                raise
            except FileExistsError:
                self.send_error(409, 'Destination already exists')
            except ExplorerError as e:
                self.send_error(e.status, str(e))
            except Exception as e:
                self.send_error(500, str(e))
                return
