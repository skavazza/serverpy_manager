"""Thread-safe, in-memory HTTP activity; never retain headers or query strings."""

from collections import OrderedDict, deque
import threading
import time
from .temp_links import redact_download_tokens


class TrafficMonitor:
    def __init__(self, clock=None, recent_limit=100, client_limit=256, retention=300):
        self.clock = clock or time.monotonic
        self.lock = threading.RLock()
        self.recent_limit = recent_limit
        self.client_limit = client_limit
        self.retention = retention
        self.connections = {}
        self.clients = OrderedDict()
        self.recent = deque(maxlen=recent_limit)
        self.serial = 0
        self.received = self.sent = self.requests = self.errors = 0
        self.samples = deque([(self.clock(), 0, 0)])

    def open_connection(self, ip):
        with self.lock:
            now = self.clock()
            self.serial += 1
            token = self.serial
            if ip not in self.clients:
                self.clients[ip] = {'ip': ip, 'connections': 0, 'requests': 0,
                                    'received': 0, 'sent': 0, 'last_seen': now}
            client = self.clients[ip]
            client['connections'] += 1
            client['last_seen'] = now
            self.clients.move_to_end(ip)
            self.connections[token] = {'ip': ip, 'received': 0, 'sent': 0,
                                       'baseline': (0, 0), 'request': None}
            self._prune(now)
            return token

    def set_client_ip(self, token, ip):
        with self.lock:
            connection = self.connections[token]
            previous_ip = connection['ip']
            if previous_ip == ip:
                return
            now = self.clock()
            previous_client = self.clients[previous_ip]
            previous_client['connections'] -= 1
            if ip not in self.clients:
                self.clients[ip] = {'ip': ip, 'connections': 0, 'requests': 0,
                                    'received': 0, 'sent': 0, 'last_seen': now}
            client = self.clients[ip]
            received, sent = connection['received'] - connection['baseline'][0], connection['sent'] - connection['baseline'][1]
            previous_client['received'] -= received
            previous_client['sent'] -= sent
            client['received'] += received
            client['sent'] += sent
            client['connections'] += 1
            client['last_seen'] = now
            self.clients.move_to_end(ip)
            connection['ip'] = ip
            self._prune(now)

    def begin_cycle(self, token):
        with self.lock:
            connection = self.connections[token]
            connection['baseline'] = connection['received'], connection['sent']

    def start_request(self, token, method, path):
        with self.lock:
            connection = self.connections[token]
            # Paths preserve the public mount prefix. Queries may contain secrets.
            path = redact_download_tokens(path.split('?', 1)[0].split('#', 1)[0])[:512]
            connection['request'] = {
                'id': token, 'ip': connection['ip'], 'method': method[:20],
                'path': path, 'started': self.clock(), 'status': None,
                'interrupted': False,
            }
            self.requests += 1
            self.clients[connection['ip']]['requests'] += 1

    def add_bytes(self, token, direction, amount):
        if amount <= 0:
            return
        with self.lock:
            connection = self.connections.get(token)
            if connection is None:
                return
            client = self.clients[connection['ip']]
            connection[direction] += amount
            client[direction] += amount
            client['last_seen'] = self.clock()
            self.clients.move_to_end(connection['ip'])
            if direction == 'received':
                self.received += amount
            else:
                self.sent += amount

    def set_status(self, token, status):
        with self.lock:
            request = self.connections[token]['request']
            if request is not None and status >= 200:
                request['status'] = status

    def interrupt(self, token):
        with self.lock:
            connection = self.connections.get(token)
            if connection and connection['request'] is not None:
                connection['request']['interrupted'] = True

    def _request_snapshot(self, connection, now, active):
        result = dict(connection['request'])
        result['elapsed'] = max(0, now - result.pop('started'))
        received, sent = connection['baseline']
        result['received'] = connection['received'] - received
        result['sent'] = connection['sent'] - sent
        result['active'] = active
        return result

    def finish_request(self, token):
        with self.lock:
            connection = self.connections.get(token)
            if connection and connection['request'] is not None:
                request = self._request_snapshot(connection, self.clock(), False)
                if request['status'] is None:
                    request['interrupted'] = True
                if request['interrupted'] or request['status'] >= 400:
                    self.errors += 1
                self.recent.appendleft(request)
                connection['request'] = None

    def close_connection(self, token):
        with self.lock:
            self.finish_request(token)
            connection = self.connections.pop(token, None)
            if connection:
                self.clients[connection['ip']]['connections'] -= 1
            self._prune(self.clock())

    def _prune(self, now):
        for ip, client in list(self.clients.items()):
            if not client['connections'] and now - client['last_seen'] > self.retention:
                del self.clients[ip]
        if len(self.clients) > self.client_limit:
            for ip in list(self.clients):
                if len(self.clients) <= self.client_limit:
                    break
                if not self.clients[ip]['connections']:
                    del self.clients[ip]

    def snapshot(self):
        with self.lock:
            now = self.clock()
            self._prune(now)
            if now - self.samples[-1][0] >= 0.25:
                self.samples.append((now, self.received, self.sent))
            while len(self.samples) > 1 and self.samples[1][0] <= now - 5:
                self.samples.popleft()
            then, received, sent = self.samples[0]
            duration = now - then
            active = [self._request_snapshot(c, now, True) for c in self.connections.values() if c['request']]
            clients = []
            for client in reversed(list(self.clients.values())):
                item = dict(client)
                item['active_requests'] = sum(request['ip'] == item['ip'] for request in active)
                item['last_seen'] = max(0, now - item['last_seen'])
                clients.append(item)
            return {
                'connections': len(self.connections), 'active_clients': sum(c['connections'] > 0 for c in clients),
                'active_requests': len(active), 'requests': self.requests, 'errors': self.errors,
                'received': self.received, 'sent': self.sent,
                'receive_rate': (self.received - received) / duration if duration >= 0.25 else 0,
                'send_rate': (self.sent - sent) / duration if duration >= 0.25 else 0,
                'clients': clients, 'activity': active + list(self.recent),
            }


class CountingStream:
    """Delegate stream operations and count bytes consumed or successfully written."""

    def __init__(self, stream, monitor, token, direction):
        self.stream, self.monitor, self.token, self.direction = stream, monitor, token, direction

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def _read(self, method, *arguments):
        try:
            data = getattr(self.stream, method)(*arguments)
        except OSError:
            self.monitor.interrupt(self.token)
            raise
        self.monitor.add_bytes(self.token, self.direction, len(data))
        if method == 'read' and arguments[0] > 0 and len(data) < arguments[0]:
            self.monitor.interrupt(self.token)
        return data

    def read(self, size=-1):
        return self._read('read', size)

    def readline(self, size=-1):
        return self._read('readline', size)

    def read1(self, size=-1):
        return self._read('read1', size)

    def write(self, data):
        try:
            count = self.stream.write(data)
        except OSError:
            self.monitor.interrupt(self.token)
            raise
        self.monitor.add_bytes(self.token, self.direction, len(data) if count is None else count)
        return count
