"""Camera viewer endpoints; authorization is performed by the main handler."""

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .camera import CAMERA_PREFIX


class CameraHTTP:
    def is_camera_request(self):
        route = urlsplit(getattr(self, 'path', '')).path
        return not self.url_prefix and (route == CAMERA_PREFIX.rstrip('/') or route.startswith(CAMERA_PREFIX))

    def serve_camera(self, head_only=False):
        if not self.is_camera_request():
            return False
        route = urlsplit(self.path).path
        if route == CAMERA_PREFIX.rstrip('/'):
            self.send_response(302)
            self.send_header('Location', CAMERA_PREFIX)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return True
        if route == CAMERA_PREFIX + 'frame.jpg':
            frame = self.server.camera.snapshot_details()
            if frame is None:
                self.send_response(503)
                self.send_header('Retry-After', '1')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return True
            content = frame['jpeg']
            content_type = 'image/jpeg'
        elif route == CAMERA_PREFIX + 'audio.pcm':
            query = parse_qs(urlsplit(self.path).query)
            try:
                after = int(query.get('after', [''])[0])
            except ValueError:
                after = None
            chunk = self.server.camera.audio.read(query.get('session', [''])[0], after)
            if chunk is None:
                self.send_response(503)
                self.send_header('Retry-After', '1')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return True
            session, offset, rate, channels, content = chunk
            content_type = 'application/octet-stream'
        else:
            asset = {
                CAMERA_PREFIX: ('camera.html', 'text/html; charset=utf-8'),
                CAMERA_PREFIX + 'viewer.js': ('camera.js', 'text/javascript; charset=utf-8'),
                CAMERA_PREFIX + 'viewer.css': ('camera.css', 'text/css; charset=utf-8'),
            }.get(route)
            if asset is None:
                self.send_error(404, 'Camera resource not found')
                return True
            filename, content_type = asset
            content = (Path(__file__).resolve().parent.parent / 'templates' / filename).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        if route == CAMERA_PREFIX + 'frame.jpg':
            self.send_header('X-Camera-Frame-ID', frame['frame_id'])
            self.send_header('X-Camera-Published-FPS', f"{frame['published_fps']:.2f}")
        if route == CAMERA_PREFIX + 'audio.pcm':
            self.send_header('X-Audio-Session', session)
            self.send_header('X-Audio-Offset', str(offset))
            self.send_header('X-Audio-Rate', str(rate))
            self.send_header('X-Audio-Channels', str(channels))
        self.end_headers()
        if not head_only:
            self.wfile.write(content)
        return True
