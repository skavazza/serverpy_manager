import socketserver
import threading
import ssl
import os
from .handlers import CustomHandler
from .explorer import FileExplorer
from .response_headers import validate_response_headers
from .shares import validate_shared_folders
from .traffic import TrafficMonitor
from .temp_links import TemporaryLinks
from .transfers import TransferMonitor
from .camera import CameraFeed
from .access import validate_access_config

class ReusableTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

class ServerManager:
    """
    Manages the lifecycle of the HTTP server.
    """
    def __init__(self):
        self.httpd = None
        self.thread = None
        self.is_running = False
        self.last_error = None
        self.traffic = TrafficMonitor()
        self.links = TemporaryLinks()
        self.transfers = TransferMonitor()
        self.camera = CameraFeed()

    def start_server(self, host, port, directory, **config):
        """
        Starts the server in a separate thread.
        """
        if self.is_running:
            return False, "Server is already running."
        self.last_error = None
        self.camera.stop()

        # Prepare configuration for the handler
        config['host'] = host
        config['port'] = port
        
        try:
            config['custom_headers'] = validate_response_headers(config.get('custom_headers', {}))
            config['shared_folders'] = validate_shared_folders(config.get('shared_folders', []))
            validate_access_config(config, directory)
            context = None
            if config.get('use_tls'):
                cert_file = config.get('cert_file')
                if not cert_file or not os.path.isfile(cert_file):
                    raise ValueError('Valid certificate file required for TLS.')
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(cert_file, password=lambda: '')
            # Create the server instance
            self.httpd = ReusableTCPServer((host, port), CustomHandler)
            actual_port = self.httpd.server_address[1]
            config['port'] = actual_port
            
            # Attach config and trackers to the server object so the handler can access them
            self.httpd.app_config = config
            self.httpd.camera = self.camera
            self.traffic = TrafficMonitor()
            self.httpd.traffic = self.traffic
            self.links = TemporaryLinks()
            self.httpd.links = self.links
            self.transfers = TransferMonitor()
            self.httpd.transfers = self.transfers
            self.httpd.ip_tracker = {}
            self.httpd.ip_tracker_lock = threading.Lock()
            self.httpd.directory = directory # Standard attribute for SimpleHTTPRequestHandler
            self.httpd.explorer = FileExplorer(directory)
            self.httpd.shared_explorers = {
                item['name']: FileExplorer(item['path']) for item in config['shared_folders']
            }

            # SSL/TLS Setup
            if context:
                self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)

            # Start the server thread
            self.is_running = True
            self.thread = threading.Thread(target=self._serve_forever, daemon=True)
            self.thread.start()
            
            return True, f"Server started successfully at {host or '0.0.0.0'}:{actual_port}"
        except Exception as e:
            self.last_error = e
            if self.httpd:
                self.httpd.server_close()
                self.httpd = None
            self.thread = None
            self.is_running = False
            return False, f"Error starting server: {e}"

    def _serve_forever(self):
        try:
            self.httpd.serve_forever()
        except Exception as e:
            print(f"Server thread closed: {e}")

    def stop_server(self):
        """
        Shuts down the server and joins the thread.
        """
        self.links.clear()
        self.camera.stop()
        self.transfers.cancel_all()
        if self.httpd:
            if self.thread and self.thread.is_alive():
                self.httpd.shutdown()
            self.httpd.server_close()
        self.is_running = False
        self.httpd = None
        if self.thread:
            self.thread.join(timeout=2)
            self.thread = None
