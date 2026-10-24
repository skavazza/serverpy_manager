import tempfile
import http.client
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from src.core.response_headers import validate_response_headers
from src.core.server import ServerManager


class TestResponseHeaders(unittest.TestCase):
    def test_invalid_headers_are_rejected(self):
        for headers in ([('Bad Name', 'test')], [('X-Test', 'a\r\nInjected: value')],
                        [('X-Test', 'a\x00b')], [('X-Test', '\u2603')],
                        [('Content-Length', '50')], [('Transfer-Encoding', 'chunked')],
                        [('Access-Control-Allow-Origin', '*')], [('Set-Cookie', 'a=b')],
                        [('X-Test', 'a'), ('x-test', 'b')]):
            with self.subTest(headers=headers), self.assertRaises(ValueError):
                validate_response_headers(headers)

    def test_headers_on_pages_files_apis_errors_and_head(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'sample.txt').write_text('sample', encoding='utf-8')
            server = ServerManager()
            started, message = server.start_server('127.0.0.1', 0, root, render_pages=True, allow_mod=True,
                custom_headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'},
                cors_config={'origin': 'https://example.com'}, redirections=[('/old', '/', 302)])
            self.assertTrue(started, message)
            base = f'http://127.0.0.1:{server.httpd.server_address[1]}'
            try:
                for path, method in (('/', 'GET'), ('/sample.txt', 'GET'), ('/sample.txt', 'HEAD'),
                                     ('/api/read?path=sample.txt', 'GET'), ('/', 'OPTIONS'), ('/missing.txt', 'GET')):
                    with self.subTest(path=path, method=method):
                        request = urllib.request.Request(base + path, method=method)
                        try:
                            response = urllib.request.urlopen(request, timeout=5)
                        except urllib.error.HTTPError as error:
                            response = error
                        with response:
                            self.assertEqual(response.status, 404 if path == '/missing.txt' else 204 if method == 'OPTIONS' else 200)
                            self.assertEqual(response.headers.get_all('Cache-Control'), ['no-store'])
                            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                            self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'https://example.com')
                            if method == 'HEAD':
                                self.assertEqual(response.read(), b'')
                            elif path == '/sample.txt':
                                self.assertEqual(response.read(), b'sample')
                connection = http.client.HTTPConnection('127.0.0.1', server.httpd.server_address[1], timeout=5)
                try:
                    connection.request('GET', '/old')
                    with connection.getresponse() as response:
                        self.assertEqual(response.status, 302)
                        self.assertEqual(response.headers['Location'], '/')
                        self.assertEqual(response.headers['Cache-Control'], 'no-store')
                finally:
                    connection.close()
            finally:
                server.stop_server()

    def test_invalid_configuration_fails_before_binding(self):
        with tempfile.TemporaryDirectory() as root:
            server = ServerManager()
            started, _ = server.start_server('127.0.0.1', 0, root, custom_headers={'Content-Length': '50'})
            self.assertFalse(started)
            self.assertIsNone(server.httpd)

    def test_unconfigured_server_does_not_add_custom_headers(self):
        with tempfile.TemporaryDirectory() as root:
            server = ServerManager()
            started, message = server.start_server('127.0.0.1', 0, root, render_pages=True)
            self.assertTrue(started, message)
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{server.httpd.server_address[1]}/', timeout=5) as response:
                    self.assertIsNone(response.headers.get('X-Content-Type-Options'))
            finally:
                server.stop_server()


if __name__ == '__main__':
    unittest.main()
