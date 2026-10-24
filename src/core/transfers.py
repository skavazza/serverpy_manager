"""Bounded session-only file-transfer progress and cooperative cancellation."""

from collections import deque
import io
import select
import threading
import time
import urllib.parse

from .temp_links import redact_download_tokens


class TransferCancelled(Exception):
    pass


class CancellableReader(io.RawIOBase):
    """Poll between bounded reads so cancellation wakes Windows timeout sockets."""
    def __init__(self, stream, connection, cancelled, idle_timeout=60):
        super().__init__()
        self.stream, self.connection, self.cancelled = stream, connection, cancelled
        self.idle_timeout = idle_timeout

    def readable(self):
        return True

    def fileno(self):
        return self.stream.fileno()

    def readinto(self, buffer):
        if not buffer:
            return 0
        socket_timeout = self.connection.gettimeout()
        idle_timeout = self.idle_timeout if socket_timeout is None else min(self.idle_timeout, socket_timeout)
        deadline = time.monotonic() + idle_timeout
        while True:
            if self.cancelled.is_set():
                raise ConnectionAbortedError('Transfer cancelled')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Client stopped sending data')
            # TLS may already hold decrypted bytes even if the socket is not ready.
            pending = getattr(self.connection, 'pending', lambda: 0)()
            if pending or select.select([self.connection], [], [], min(.2, remaining))[0]:
                if self.cancelled.is_set():
                    raise ConnectionAbortedError('Transfer cancelled')
                return self.stream.readinto(buffer)

    def close(self):
        try:
            self.stream.close()
        finally:
            super().close()


class TransferMonitor:
    def __init__(self, clock=None, history_limit=100):
        self.clock = clock or time.monotonic
        self.lock = threading.RLock()
        self.active = {}
        self.recent = deque(maxlen=history_limit)
        self.serial = 0

    def begin(self, direction, path, size, ip, cancel):
        with self.lock:
            self.serial += 1
            now = self.clock()
            # Redact before URL decoding too: bearer tokens must never enter the UI.
            path = redact_download_tokens(urllib.parse.unquote(redact_download_tokens(path.split('?', 1)[0])))[:512]
            self.active[self.serial] = dict(id=self.serial, direction=direction, path=path,
                size=size, done=0, ip=ip, started=now, state='In progress',
                cancelled=False, cancel=cancel, samples=deque([(now, 0)]))
            return self.serial

    def advance(self, token, amount):
        with self.lock:
            item = self.active[token]
            item['done'] += amount
            if item['cancelled']:
                raise TransferCancelled()
            now = self.clock()
            if now - item['samples'][-1][0] >= .25:
                item['samples'].append((now, item['done']))
            while len(item['samples']) > 1 and item['samples'][1][0] < now - 5:
                item['samples'].popleft()

    def cancel(self, token):
        with self.lock:
            item = self.active.get(token)
            if not item or item['cancelled']:
                return False
            item['cancelled'] = True
            item['state'] = 'Cancelling'
            callback = item['cancel']
        try:
            callback()
        except OSError:
            pass
        return True

    def cancel_all(self):
        with self.lock:
            tokens = list(self.active)
        for token in tokens:
            self.cancel(token)

    def complete(self, token, commit=None):
        # Serialize cancellation with publication: completed files cannot later
        # be reported as cancelled, and cancelled uploads cannot be published.
        with self.lock:
            item = self.active[token]
            if item['cancelled']:
                raise TransferCancelled()
            if item['done'] != item['size']:
                raise OSError('Incomplete transfer')
            if commit is not None:
                commit()
            self._finish(token, 'Completed')

    def fail(self, token, state='Interrupted'):
        with self.lock:
            item = self.active.get(token)
            if item:
                self._finish(token, 'Cancelled' if item['cancelled'] else state)

    def _finish(self, token, state):
        item = self.active.pop(token)
        item['state'] = state
        item['ended'] = self.clock()
        item.pop('cancel')
        self.recent.appendleft(item)

    def snapshot(self):
        with self.lock:
            now = self.clock()
            result = []
            for item in list(self.active.values()) + list(self.recent):
                elapsed = max(0, item.get('ended', now) - item['started'])
                then, done = item['samples'][0]
                duration = now - then
                rate = (item['done'] - done) / duration if duration >= .25 and 'ended' not in item else 0
                result.append({key: item[key] for key in ('id', 'direction', 'path', 'size', 'done', 'ip', 'state')} |
                    dict(elapsed=elapsed, rate=rate, remaining=(item['size'] - item['done']) / rate if rate > 0 else None,
                         active='ended' not in item))
            return result
