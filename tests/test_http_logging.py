import contextlib
import http.client
import io
import socket
import tempfile
import unittest

from src.core.server import ServerManager


class TestHTTPLogging(unittest.TestCase):
    def test_cp1252_log_cannot_break_unicode_response_or_expose_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            server = ServerManager()
            self.addCleanup(server.stop_server)
            ok, message = server.start_server('127.0.0.1', 0, directory)
            self.assertTrue(ok, message)
            output = io.BytesIO()
            console = io.TextIOWrapper(output, encoding='cp1252', write_through=True)
            connection = socket.create_connection(('127.0.0.1', server.httpd.server_address[1]), timeout=3)
            try:
                with contextlib.redirect_stdout(console):
                    # The raw request is decoded as Latin-1 by http.server. 0x81
                    # is unrepresentable in cp1252, reproducing the Windows error.
                    connection.sendall(b'GET /missing\x81 HTTP/1.1\r\nHost: localhost\r\n\r\n')
                    response = http.client.HTTPResponse(connection)
                    response.begin()
                    self.assertEqual(response.status, 404)
                    response.read()
                    from src.core.handlers import CustomHandler
                    class LogContext:
                        client_ip = '127.0.0.1'
                        client_address = ('127.0.0.1', 1)
                        def log_date_time_string(self):
                            return 'test'
                    CustomHandler.log_message(LogContext(), '/_download/SECRET_TOKEN %s', '\U0001f419')
                text = output.getvalue().decode('cp1252')
                self.assertIn('404', text)
                self.assertIn('\\x81', text)
                self.assertIn('\\U0001f419', text)
                self.assertNotIn('SECRET_TOKEN', text)
                self.assertIn('/_download/[link]', text)
            finally:
                connection.close()
                console.detach()
