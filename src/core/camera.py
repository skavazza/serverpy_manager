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
    'x-camera-fps', 'x-camera-audio',
    'x-camera-frame-id', 'x-camera-published-fps',
    'x-audio-session', 'x-audio-offset', 'x-audio-rate', 'x-audio-channels',
}


class AudioFeed:
    """Ring buffer of the most recent 16-bit PCM microphone audio, addressed by byte offset."""
    MAX_SECONDS = 5
    CATCH_UP_SECONDS = 2
    START_SECONDS = .5
    MAX_AGE = 3
    MAX_RESPONSE = 1024 * 1024
    RATES = (8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000)

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.session = None
        self.rate = 16000
        self.channels = 1
        self.chunks = deque()
        self.start_offset = 0
        self.end_offset = 0
        self.updated = 0

    def start(self, rate=16000, channels=1):
        if rate not in self.RATES or channels not in (1, 2):
            raise ValueError('Unsupported audio format.')
        with self.lock:
            self.session = uuid4().hex
            self.rate, self.channels = rate, channels
            self.chunks.clear()
            self.start_offset = self.end_offset = 0
            self.updated = 0
            return self.session

    def stop(self, session=None):
        with self.lock:
            if session is None or session == self.session:
                self.session = None
                self.chunks.clear()
                self.start_offset = self.end_offset = 0
                self.updated = 0

    def active(self):
        with self.lock:
            return self.session is not None

    def publish(self, session, data):
        with self.lock:
            frame = 2 * self.channels
            if session is None or session != self.session or not isinstance(data, bytes) or not data or len(data) % frame:
                return False
            self.chunks.append(data)
            self.end_offset += len(data)
            self.updated = self.clock()
            limit = self.rate * frame * self.MAX_SECONDS
            while self.end_offset - self.start_offset > limit and self.chunks:
                self.start_offset += len(self.chunks.popleft())
            return True

    def read(self, session=None, after=None):
        """Return (session, end_offset, rate, channels, data), or None when audio is unavailable."""
        with self.lock:
            if self.session is None or (self.updated and self.clock() - self.updated > self.MAX_AGE):
                return None
            frame = 2 * self.channels
            per_second = self.rate * frame
            if session == self.session and isinstance(after, int) and self.start_offset <= after <= self.end_offset:
                begin = max(after, self.end_offset - self.CATCH_UP_SECONDS * per_second)
            else:
                begin = max(self.start_offset, self.end_offset - int(self.START_SECONDS * per_second))
            begin -= (begin - self.start_offset) % frame
            end = min(self.end_offset, begin + self.MAX_RESPONSE)
            end -= (end - begin) % frame
            data = b''.join(self.chunks)[begin - self.start_offset:end - self.start_offset] if end > begin else b''
            return self.session, end, self.rate, self.channels, data


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
        self.audio = AudioFeed(clock)

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
                self.audio.stop()

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
