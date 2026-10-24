"""File operation errors must produce exactly one HTTP response."""

import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from src.core.explorer import ExplorerError
from src.core.server import ServerManager


class TestFileOperationResponses(unittest.TestCase):
    def test_publish_conflicts_return_one_response_and_preserve_source(self):
        with tempfile.TemporaryDirectory() as scratch:
            source = Path(scratch) / 'source.txt'
            source.write_bytes(b'original')
            server = ServerManager()
            try:
                ok, message = server.start_server('127.0.0.1', 0, scratch, allow_mod=True)
                self.assertTrue(ok, message)
                cases = (
                    ('copy', patch('src.core.file_http.shutil.copy2', side_effect=FileExistsError())),
                    ('move', patch.object(server.httpd.explorer, 'move', side_effect=ExplorerError(409, 'Destination changed'))),
                )
                for route, conflict in cases:
                    with self.subTest(route=route), conflict:
                        body = json.dumps(dict(src='/source.txt', dst='/destination.txt')).encode()
                        header = (f'POST /api/{route} HTTP/1.1\r\nHost: localhost\r\n'
                                  f'Content-Length: {len(body)}\r\nConnection: close\r\n\r\n').encode()
                        with socket.create_connection(server.httpd.server_address, timeout=3) as client:
                            client.sendall(header + body)
                            response = bytearray()
                            while True:
                                chunk = client.recv(4096)
                                if not chunk:
                                    break
                                response.extend(chunk)
                        self.assertIn(b'409', response.split(b'\r\n', 1)[0])
                        self.assertEqual(response.count(b'HTTP/1.'), 1)
                        self.assertEqual(source.read_bytes(), b'original')
                        self.assertFalse((Path(scratch) / 'destination.txt').exists())
            finally:
                server.stop_server()
