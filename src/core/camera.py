"""Thread-safe latest JPEG for a desktop-controlled camera session."""

import threading
import time
from collections import deque
from uuid import uuid4


CAMERA_PREFIX = '/_camera/'
CAMERA_HEADERS = {
    'Cache-Control': 'no-store, max-age=0',
    'Pragma': 'no-cache',
    'X-Content-Type-Options': 'nosniff',
    'Cross-Origin-Resource-Policy': 'same-origin',
    'Referrer-Policy': 'no-referrer',
    'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
}
CAMERA_RESERVED_HEADERS = {name.lower() for name in CAMERA_HEADERS} | {
    'access-control-allow-origin', 'access-control-allow-credentials',
    'content-type', 'content-length', 'expires', 'etag', 'last-modified',
    'x-camera-fps',
    'x-camera-frame-id', 'x-camera-published-fps',
}


class CameraFeed:
    MAX_BYTES = 8 * 1024 * 1024
    MAX_AGE = 3

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.session = None
        self.frame = None
        self.updated = 0
        self._fps = 5
        self.started = None
        self.timestamps = deque(maxlen=512)
        self.sequence = 0
        self.size = (0, 0)

    @property
    def fps(self):
        with self.lock:
            return self._fps

    def set_fps(self, fps):
        if type(fps) is not int or not 1 <= fps <= 30:
            raise ValueError('Camera FPS must be an integer from 1 to 30.')
        with self.lock:
            self._fps = fps

    def start(self):
        with self.lock:
            self.session = uuid4().hex
            self.frame = None
            self.updated = 0
            self.started = self.clock()
            self.timestamps.clear()
            self.sequence = 0
            self.size = (0, 0)
            return self.session

    def stop(self, session=None):
        with self.lock:
            if session is None or session == self.session:
                self.session = None
                self.frame = None
                self.updated = 0
                self.started = None
                self.timestamps.clear()
                self.size = (0, 0)

    def is_current(self, session):
        with self.lock:
            return session is not None and session == self.session

    def publish(self, session, jpeg, size=(0, 0)):
        if not isinstance(jpeg, bytes) or not 4 <= len(jpeg) <= self.MAX_BYTES or not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
            return False
        with self.lock:
            if session is None or session != self.session:
                return False
            self.frame, self.updated = jpeg, self.clock()
            self.sequence += 1
            self.timestamps.append(self.updated)
            self.size = size
            return True

    def snapshot(self):
        details = self.snapshot_details()
        return details['jpeg'] if details else None

    def _stats_locked(self, now):
        cutoff = max(self.started if self.started is not None else now, now - 5)
        while self.timestamps and self.timestamps[0] <= cutoff:
            self.timestamps.popleft()
        fresh = self.session is not None and self.frame is not None and now - self.updated <= self.MAX_AGE
        elapsed = now - cutoff
        rate = len(self.timestamps) / elapsed if fresh and elapsed >= .5 else 0
        return {'published_fps': rate, 'width': self.size[0] if fresh else 0, 'height': self.size[1] if fresh else 0}

    def stats(self):
        with self.lock:
            return self._stats_locked(self.clock())

    def snapshot_details(self):
        with self.lock:
            now = self.clock()
            if not self.session or self.frame is None or now - self.updated > self.MAX_AGE:
                return None
            return dict(self._stats_locked(now), jpeg=self.frame, frame_id=f'{self.session}:{self.sequence}')
