import http.server
import os
import html
import urllib.parse
import shutil
import json
import subprocess
import time
import io
import hashlib
import socket
import select
import ssl
import stat
import threading
import ipaddress
from collections import deque
from .explorer import ExplorerError, STATE_FOLDER
from .pwa import PWA_PREFIX, load_asset
from .shares import SHARES_PREFIX
from .traffic import CountingStream
from .link_http import TemporaryLinkHTTP, LINK_RESPONSE_HEADERS, LINK_RESERVED_HEADERS
from .temp_links import DOWNLOAD_PREFIX, redact_download_tokens
from .transfers import TransferCancelled, CancellableReader
from .uploads import StagedUpload
from .camera_http import CameraHTTP
from .camera import CAMERA_HEADERS, CAMERA_RESERVED_HEADERS
from .access import FolderAccessHTTP, PERMISSIONS


def resolve_client_ip(peer_ip, headers, cloudflare_tunnel=False):
    if not cloudflare_tunnel:
        return peer_ip
    try:
        peer_address = ipaddress.ip_address(peer_ip)
        if isinstance(peer_address, ipaddress.IPv6Address) and peer_address.ipv4_mapped:
            peer_address = peer_address.ipv4_mapped
        if not peer_address.is_loopback:
            return peer_ip
        get_all = getattr(headers, 'get_all', None)
        values = get_all('CF-Connecting-IP', []) if callable(get_all) else []
        if len(values) > 1:
            return peer_ip
        forwarded_ip = (values[0] if values else headers.get('CF-Connecting-IP', '')).strip()
        if not forwarded_ip or ',' in forwarded_ip:
            return peer_ip
        return str(ipaddress.ip_address(forwarded_ip))
    except ValueError:
        return peer_ip


class CustomHandler(FolderAccessHTTP, CameraHTTP, TemporaryLinkHTTP, http.server.SimpleHTTPRequestHandler):
    """
    Custom HTTP Request Handler for the File Manager.
    Handles standard file serving plus API endpoints for file management and system intents.
    """
    def __init__(self, *args, **kwargs):
        # The server object is the 3rd argument in *args (request, client_address, server)
        server = args[2]
        directory = getattr(server, 'directory', os.getcwd())
        self.config = server.app_config
        self.explorer = server.explorer
        self.url_prefix = ''
        super().__init__(*args, directory=directory, **kwargs)

    def setup(self):
        super().setup()
        self.transfer_cancelled = threading.Event()
        raw_reader = self.rfile.detach()
        self.rfile = io.BufferedReader(CancellableReader(raw_reader, self.connection, self.transfer_cancelled))
        self.traffic_id = self.server.traffic.open_connection(self.client_address[0])
        self.rfile = CountingStream(self.rfile, self.server.traffic, self.traffic_id, 'received')
        self.wfile = CountingStream(self.wfile, self.server.traffic, self.traffic_id, 'sent')

    def handle_one_request(self):
        self.server.traffic.begin_cycle(self.traffic_id)
        try:
            super().handle_one_request()
        finally:
            self.server.traffic.finish_request(self.traffic_id)

    def finish(self):
        try:
            super().finish()
        finally:
            self.server.traffic.close_connection(self.traffic_id)

    def send_response(self, code, message=None):
        self.server.traffic.set_status(self.traffic_id, code)
        super().send_response(code, message)

    def parse_request(self):
        # A handler may process more than one request on the same connection.
        self.config = self.server.app_config
        self.explorer = self.server.explorer
        self.directory = self.server.directory
        self.url_prefix = ''
        self.route_error = None
        self.mount_redirect = False
        self.response_length = None
        if not super().parse_request():
            return False
        self.server.traffic.set_client_ip(self.traffic_id, self.client_ip)
        self.server.traffic.start_request(self.traffic_id, self.command, self.path)
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path.startswith(SHARES_PREFIX):
            alias, separator, relative = parsed.path[len(SHARES_PREFIX):].partition('/')
            if alias != urllib.parse.unquote(alias):
                self.route_error = (404, 'Shared folder not found')
                return True
            item = next((item for item in self.config.get('shared_folders', []) if item['name'] == alias), None)
            if item is None:
                self.route_error = (404, 'Shared folder not found')
                return True
            self.url_prefix = SHARES_PREFIX + alias
            self.mount_redirect = not separator
            self.config = dict(self.config, allow_mod=bool(self.config.get('allow_mod') and item['writable']), enable_intents=False)
            self.explorer = self.server.shared_explorers[alias]
            self.directory = str(self.explorer.root)
            if not os.path.isdir(self.directory):
                self.route_error = (503, 'Shared folder is unavailable')
            self.path = urllib.parse.urlunsplit(('', '', '/' + relative, parsed.query, ''))
        return True

    @property
    def client_ip(self):
        return resolve_client_ip(
            self.client_address[0],
            getattr(self, 'headers', {}),
            self.config.get('cloudflare_tunnel', False),
        )

    def send_header(self, keyword, value):
        if keyword.lower() == 'content-length':
            self.response_length = int(value)
        if keyword.lower() == 'location' and self.url_prefix and value.startswith('/') and not value.startswith(self.url_prefix + '/'):
            value = self.url_prefix + value
        super().send_header(keyword, value)
    
    def safe_resolve_path(self, user_path):
        """
        Safely resolves a user-supplied relative path against self.directory.
        Returns the normalized absolute path if it is inside self.directory, else None.
        """
        try:
            return str(self.explorer.resolve(user_path or '/', allow_root=True))
        except (ExplorerError, OSError, ValueError):
            return None

    def check_security(self):
        if self.route_error:
            self.send_error(*self.route_error)
            return False
        config = self.config
        relative = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        if not self.safe_resolve_path(relative):
            self.send_error(403, 'Access denied')
            return False
        client_ip = self.client_ip
        
        if config.get('whitelist') and client_ip not in config['whitelist']:
            self.send_error(403, "IP not whitelisted")
            return False
            
        if config.get('verify_host'):
            raw_host = self.headers.get('Host', '').strip()
            host_only = raw_host.split(':')[0]
            configured_host = config.get('host', '').strip()
            configured_port = str(config.get('port', ''))

            allowed = set()
            if configured_host:
                allowed.add(configured_host)
                allowed.add(f"{configured_host}:{configured_port}")
                if configured_host in ("127.0.0.1", "localhost"):
                    allowed.update({"127.0.0.1", "localhost", f"127.0.0.1:{configured_port}", f"localhost:{configured_port}"})
            elif configured_port:
                allowed.update({"localhost", "127.0.0.1", f"localhost:{configured_port}", f"127.0.0.1:{configured_port}"})

            public_host = (
                config.get('cloudflare_hostname', '').strip().rstrip('.').lower()
                if config.get('cloudflare_tunnel') else ''
            )
            host_allowed = raw_host in allowed or host_only in allowed
            if public_host and host_only.rstrip('.').lower() == public_host:
                host_allowed = True
            if (configured_host or public_host) and not host_allowed:
                self.send_error(400, "Bad Request: Invalid Host header")
                return False
                
        if config.get('rate_limit') is not None:
            now = time.time()
            lock = getattr(self.server, 'ip_tracker_lock', None)
            if lock:
                lock.acquire()
            try:
                if client_ip not in self.server.ip_tracker:
                    self.server.ip_tracker[client_ip] = deque()
                
                tracker = self.server.ip_tracker[client_ip]
                while tracker and tracker[0] < now - 1.0:
                    tracker.popleft()
                    
                if len(tracker) >= config['rate_limit']:
                    self.send_error(429, "Too Many Requests")
                    return False
                
                tracker.append(now)
            finally:
                if lock:
                    lock.release()

        return True

    def handle_redirections(self):
        if self.mount_redirect:
            self.send_response(301)
            self.send_header('Location', self.url_prefix + '/')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return True
        redirections = self.config.get('redirections')
        if not redirections:
            return False
        for src, dest, code in redirections:
            if self.path == src:
                self.send_response(code)
                self.send_header('Location', dest)
                self.end_headers()
                return True
        return False

    def send_cors_headers(self):
        if self.is_camera_request():
            return
        if self.is_link_request():
            return
        cors_config = self.config.get('cors_config')
        if not cors_config:
            return
        self.send_header('Access-Control-Allow-Origin', cors_config.get('origin', '*'))
        self.send_header('Access-Control-Allow-Methods', cors_config.get('methods', 'GET, POST, OPTIONS, PUT, DELETE'))
        self.send_header('Access-Control-Allow-Headers', cors_config.get('headers', 'Content-Type, Authorization'))

    def end_headers(self):
        self.send_cors_headers()
        custom = self.config.get('custom_headers', {})
        if self.is_camera_request():
            custom = {name: value for name, value in custom.items() if name.lower() not in CAMERA_RESERVED_HEADERS}
            self.send_header('X-Camera-FPS', str(self.server.camera.fps))
            for name, value in CAMERA_HEADERS.items():
                self.send_header(name, value)
        if self.is_link_request():
            custom = {name: value for name, value in custom.items() if name.lower() not in LINK_RESERVED_HEADERS}
            for name, value in LINK_RESPONSE_HEADERS.items():
                self.send_header(name, value)
        if custom:
            names = {name.lower().encode('ascii') for name in custom}
            self._headers_buffer = [line for line in self._headers_buffer
                                    if line.split(b':', 1)[0].lower() not in names]
            for name, value in custom.items():
                self.send_header(name, value)
        super().end_headers()

    def do_OPTIONS(self):
        if not self.check_security():
            return
        self.send_response(204)
        self.end_headers()

    def guess_type(self, path):
        ctype = super().guess_type(path)
        custom_charset = self.config.get('custom_charset')
        if custom_charset and ctype.startswith('text/'):
            return f"{ctype}; charset={custom_charset}"
        return ctype

    def cancel_transfer(self):
        self.transfer_cancelled.set()
        self.connection.shutdown(socket.SHUT_RDWR)

    def copyfile(self, source, outputfile):
        try:
            info = os.fstat(source.fileno())
        except (AttributeError, OSError, ValueError):
            return super().copyfile(source, outputfile)
        if not stat.S_ISREG(info.st_mode):
            return super().copyfile(source, outputfile)
        size = self.response_length if self.response_length is not None else max(0, info.st_size - source.tell())
        monitor = self.server.transfers
        token = monitor.begin('Download', self.url_prefix + self.path, size,
                              self.client_ip, self.cancel_transfer)
        original_timeout = self.connection.gettimeout()
        try:
            # A bounded nonblocking sender can notice cancellation even when
            # a Windows client stops reading and the send buffer fills up.
            self.connection.setblocking(False)
            remaining = size
            while remaining:
                monitor.advance(token, 0)
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    raise OSError('Incomplete transfer')
                self.send_transfer_chunk(chunk, monitor, token)
                remaining -= len(chunk)
            monitor.complete(token)
        except (OSError, TransferCancelled):
            self.server.traffic.interrupt(self.traffic_id)
            monitor.fail(token)
            self.close_connection = True
        finally:
            self.connection.settimeout(original_timeout)

    def send_transfer_chunk(self, chunk, monitor, token):
        view = memoryview(chunk)
        deadline = time.monotonic() + 60
        while view:
            monitor.advance(token, 0)
            wait_for_read = False
            try:
                sent = self.connection.send(view)
                if not sent:
                    raise ConnectionError('Client disconnected')
                self.server.traffic.add_bytes(self.traffic_id, 'sent', sent)
                monitor.advance(token, sent)
                view = view[sent:]
                deadline = time.monotonic() + 60
                continue
            except ssl.SSLWantReadError:
                wait_for_read = True
            except (BlockingIOError, ssl.SSLWantWriteError):
                pass
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Client stopped receiving data')
            select.select([self.connection] if wait_for_read else [],
                          [] if wait_for_read else [self.connection], [], min(.2, remaining))

    def list_directory(self, path):
        config = self.config
        if not config.get('render_pages'):
            self.send_error(403, "Directory listing forbidden")
            return None
        try:
            items = os.listdir(path)
        except OSError:
            self.send_error(404, "No permission to list directory")
            return None
        items.sort(key=lambda a: a.lower())
        
        # Path to template relative to this file
        template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "web_interface.html")
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
            with open(os.path.join(os.path.dirname(template_path), 'explorer.css'), encoding='utf-8') as f:
                template = template.replace('{styles}', f.read())
        else:
            template = "<html><body><h1>{path}</h1><ul>{items}</ul></body></html>"

        displaypath = html.escape(urllib.parse.unquote(self.path))
        
        items_html = []
        if self.path != '/':
            items_html.append('''
                <a href=".." class="card">
                    <div class="icon-container">
                        <span class="icon">🔙</span>
                    </div>
                    <span class="name" data-i18n="Parent Directory">Parent Directory</span>
                    <span class="meta"></span>
                </a>
            ''')
        
        for name in items:
            if name.casefold() == STATE_FOLDER:
                continue
            fullname = os.path.join(path, name)
            displayname = linkname = name
            icon = "📄"
            meta = ""
            size = 0
            modified = 0
            is_dir = os.path.isdir(fullname)
            
            if os.path.isdir(fullname):
                displayname = name + "/"
                linkname = name + "/"
                icon = "📁"
            elif name.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp')) and (getattr(self, 'folder_permissions', None) is None or 'download' in self.folder_permissions):
                icon = f'<img src="{urllib.parse.quote(linkname)}" class="thumb">'
            elif name.lower().endswith(('.mp4', '.mkv', '.avi', '.mov')):
                icon = "🎥"
            elif name.lower().endswith(('.mp3', '.wav', '.flac')):
                icon = "🎵"
            elif name.lower().endswith(('.zip', '.rar', '.7z', '.tar', '.gz')):
                icon = "📦"
            elif name.lower().endswith(('.html', '.css', '.js', '.py', '.c', '.cpp', '.h', '.sh')):
                icon = "💻"
            elif name.lower().endswith(('.pdf')):
                icon = "📕"
            
            try:
                st = os.stat(fullname)
                modified = st.st_mtime
                if not os.path.isdir(fullname):
                    size = st.st_size
                    if size < 1024: meta = f"{size} B"
                    elif size < 1024*1024: meta = f"{size/1024:.1f} KB"
                    else: meta = f"{size/1024/1024:.1f} MB"
            except:
                pass

            escaped_linkname = html.escape(linkname, quote=True)
            escaped_displayname = html.escape(displayname)
            quoted_url = urllib.parse.quote(linkname)
            items_html.append(f'''
                <div class="card" data-name="{escaped_linkname}" data-size="{size}" data-modified="{modified}" data-directory="{'true' if is_dir else 'false'}" data-url="{quoted_url}" draggable="true" onclick="toggleSelect(this, this.dataset.name, event)" ondblclick="openItem(this)">
                    <span class="select-dot"></span>
                    <div class="icon-container">
                        <span class="icon">{icon}</span>
                    </div>
                    <span class="name">{escaped_displayname}</span>
                    <span class="meta">{meta}</span>
                    <time class="modified" data-timestamp="{modified}"></time>
                </div>
            ''')

        intents_html = ""
        if config.get('enable_intents') and getattr(self, 'folder_user', None) is None:
            intents_html = """
            <div class="terminal-container" onclick="event.stopPropagation()">
                <div class="terminal-header">
                    <span>Terminal / Intent Sender</span>
                    <button onclick="document.getElementById('terminal-output').innerHTML=''" style="background:none; border:1px solid #444; color:#888; font-size:9px; cursor:pointer; padding: 2px 5px; border-radius:3px;">CLEAR</button>
                </div>
                <div class="terminal-body" onclick="document.getElementById('cmd-input').focus()">
                    <div id="terminal-output"></div>
                    <div class="terminal-input-row">
                        <span>$</span>
                        <input type="text" id="cmd-input" placeholder="Enter system command..." onkeyup="if(event.key==='Enter') sendIntent()" autocomplete="off">
                    </div>
                </div>
            </div>
            """

        allowed = set(PERMISSIONS) if getattr(self, 'folder_permissions', None) is None else set(self.folder_permissions)
        if not config.get('allow_mod'):
            allowed -= {'upload', 'edit', 'delete'}
        content = template.replace("{title}", displaypath) \
                         .replace("{permissions}", html.escape(json.dumps(sorted(allowed)), quote=True)) \
                         .replace("{url_prefix}", self.url_prefix) \
                         .replace("{shares_nav}", self.shared_folder_links()) \
                         .replace("{root_id}", hashlib.sha256(os.path.realpath(self.directory).encode('utf-8')).hexdigest()[:16]) \
                         .replace("{allow_mod}", 'true' if config.get('allow_mod') else 'false') \
                         .replace("{path}", displaypath) \
                         .replace("{items}", "".join(items_html)) \
                         .replace("{intents_ui}", intents_html) \
                         .encode('utf-8')
        
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        return io.BytesIO(content)

    def shared_folder_links(self):
        items = self.config.get('shared_folders', [])
        if not items:
            return ''
        user = getattr(self, 'folder_user', None)
        links = ['<a href="/" class="tool-btn" data-i18n="Main folder">Main folder</a>'] if user is None or 'view' in user['grants'].get('/', []) else []
        for item in items:
            if user is not None and 'view' not in user['grants'].get(item['name'], []):
                continue
            name = html.escape(item['name'])
            current = ' aria-current="page"' if self.url_prefix == SHARES_PREFIX + item['name'] else ''
            links.append(f'<a class="tool-btn"{current} href="{SHARES_PREFIX}{item["name"]}/">{name}</a>')
        return '<nav class="shared-folders" aria-label="Shared folders" data-i18n-aria="Shared folders">' + ''.join(links) + '</nav>'

    def do_PUT(self):
        config = self.config
        if not self.check_security(): return
        if self.serve_temporary_link(): return
        if self.handle_redirections(): return
        if not self.authorize_request(): return
        if not config.get('allow_mod'):
            self.send_error(405, "Method Not Allowed")
            return
        
        path = self.translate_path(self.path)
        if not self.require_permission('edit' if os.path.lexists(path) else 'upload'): return
        base = os.path.abspath(self.directory)
        if not (path == base or path.startswith(base + os.sep)):
            self.send_error(403, "Access denied")
            return
            
        lengths = self.headers.get_all('Content-Length', [])
        if self.headers.get('Transfer-Encoding') or len(lengths) > 1:
            self.send_error(400, 'Invalid upload framing')
            return
        if not lengths:
            self.send_error(411, 'Content-Length required')
            return
        raw_length = lengths[0]
        if len(raw_length) > 20 or not raw_length.isascii() or not raw_length.isdigit():
            self.send_error(400, 'Invalid Content-Length')
            return
        length = int(raw_length)
        token = None
        monitor = self.server.transfers
        try:
            relative = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
            exclusive = self.headers.get('If-None-Match') == '*' or (self.folder_permissions is not None and 'edit' not in self.folder_permissions)
            with StagedUpload(self.explorer, relative, exclusive) as upload:
                token = monitor.begin('Upload', self.url_prefix + self.path, length,
                                      self.client_ip, self.cancel_transfer)
                self.connection.settimeout(60)
                remaining = length
                while remaining > 0:
                    monitor.advance(token, 0)
                    chunk = self.rfile.read1(min(remaining, 64 * 1024))
                    if not chunk:
                        raise ConnectionError('Incomplete upload')
                    upload.stream.write(chunk)
                    monitor.advance(token, len(chunk))
                    remaining -= len(chunk)
                monitor.complete(token, upload.commit)
            self.send_response(201, "Created")
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (OSError, ExplorerError, TransferCancelled) as error:
            if token is not None:
                monitor.fail(token, 'Interrupted' if isinstance(error, (ConnectionError, TimeoutError, TransferCancelled)) else 'Failed')
            self.close_connection = True
            status = error.status if isinstance(error, ExplorerError) else 408 if isinstance(error, TimeoutError) else 400 if isinstance(error, (ConnectionError, TransferCancelled)) else 500
            try:
                self.send_error(status, str(error) or 'Upload cancelled')
            except OSError:
                pass

    def do_DELETE(self):
        config = self.config
        if not self.check_security(): return
        if self.serve_temporary_link(): return
        if self.handle_redirections(): return
        if not self.authorize_request(): return
        if not config.get('allow_mod'):
            self.send_error(405, "Method Not Allowed")
            return
        
        path = self.translate_path(self.path)
        base = os.path.abspath(self.directory)
        if not (path == base or path.startswith(base + os.sep)) or path == base:
            self.send_error(403, "Access denied")
            return
        try:
            relative = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
            self.explorer.trash(relative)
            self.send_response(204, "No Content")
            self.send_header("Content-Length", "0")
            self.end_headers()
        except ExplorerError as e:
            self.send_error(e.status, str(e))
        except Exception as e:
            self.send_error(404, str(e))

    def do_HEAD(self):
        config = self.config
        if not self.check_security(): return
        if self.serve_temporary_link(): return
        if self.handle_redirections(): return
        if not self.authorize_request(): return
        if self.serve_pwa_asset(head_only=True): return
        if self.serve_camera(head_only=True): return
        super().do_HEAD()

    def serve_pwa_asset(self, head_only=False):
        route = urllib.parse.urlparse(self.path).path
        if not route.startswith(PWA_PREFIX):
            return False
        if not self.config.get('render_pages'):
            self.send_error(403, 'Directory listing forbidden')
            return True
        asset = load_asset(route)
        if asset is None:
            self.send_error(404, 'PWA asset not found')
            return True
        content, content_type = asset
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if route == PWA_PREFIX + 'sw.js':
            self.send_header('Service-Worker-Allowed', '/')
        self.end_headers()
        if not head_only:
            self.wfile.write(content)
        return True

    def do_GET(self):
        config = self.config
        if not self.check_security(): return
        if self.serve_temporary_link(): return
        if self.handle_redirections(): return
        if not self.authorize_request(): return
        if self.serve_pwa_asset(): return
        if self.serve_camera(): return

        route = urllib.parse.urlparse(self.path).path
        if route == '/api/ping':
            if not config.get('render_pages'):
                self.send_error(403, 'Directory listing forbidden')
                return
            self.send_json({'ok': True}, cache_control='no-store')
            return
        if route in ('/api/search', '/api/trash', '/api/moves'):
            if not config.get('render_pages'):
                self.send_error(403, 'Directory listing forbidden')
                return
            try:
                if route == '/api/search':
                    params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    result = self.explorer.search(params.get('q', [''])[0], params.get('path', ['/'])[0])
                elif route == '/api/trash':
                    result = {'items': self.explorer.list_trash()}
                else:
                    result = {'items': self.explorer.list_moves()}
                self.send_json(result)
            except ExplorerError as error:
                self.send_error(error.status, str(error))
            except (OSError, ValueError):
                self.send_error(500, 'Unable to load explorer data')
            return

        if urllib.parse.urlparse(self.path).path == '/api/folders':
            self.list_folders()
            return

        if self.path.startswith('/api/read'):
            if not config.get('allow_mod'):
                self.send_error(405, "Not allowed")
                return
            
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            file_rel = params.get('path', [''])[0]
            file_path = self.safe_resolve_path(file_rel)
            
            if not file_path or not os.path.isfile(file_path):
                self.send_error(404, "File not found or access denied")
                return
                
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                encoded_content = content.encode('utf-8')
                self.send_response(200)
                self.send_header("Content-type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded_content)))
                self.end_headers()
                self.wfile.write(encoded_content)
            except Exception as e:
                self.send_error(500, str(e))
            return

        if self.path.startswith('/api/zip'):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            folder_rel = params.get('path', [''])[0]
            folder_path = self.safe_resolve_path(folder_rel)
            
            if not folder_path or not os.path.isdir(folder_path):
                self.send_error(404, "Directory not found or access denied")
                return

            mem_file = io.BytesIO()
            try:
                import zipfile
                with zipfile.ZipFile(mem_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for root, dirs, files in os.walk(folder_path):
                        dirs[:] = [name for name in dirs if name.casefold() != STATE_FOLDER and self.safe_resolve_path(os.path.relpath(os.path.join(root, name), self.directory))]
                        for file in files:
                            abs_path = os.path.join(root, file)
                            if not self.safe_resolve_path(os.path.relpath(abs_path, self.directory)):
                                continue
                            rel_path = os.path.relpath(abs_path, folder_path)
                            zf.write(abs_path, rel_path)
                
                zip_data = mem_file.getvalue()
                mem_file.close()
                self.send_response(200)
                self.send_header("Content-type", "application/zip")
                self.send_header("Content-Disposition", 'attachment; filename="archive.zip"')
                self.send_header("Content-Length", str(len(zip_data)))
                self.end_headers()
                self.wfile.write(zip_data)
            except Exception as e:
                self.send_error(500, str(e))
            return

        super().do_GET()

    def list_folders(self):
        """List one level of the navigation tree, within the served root."""
        if not self.config.get('render_pages'):
            self.send_error(403, "Directory listing forbidden")
            return
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        # parse_qs already decodes the query; literal percent signs in names must survive.
        relative = params.get('path', ['/'])[0].lstrip('/\\')
        base = os.path.realpath(self.directory)
        try:
            target = os.path.realpath(os.path.join(base, relative))
            if os.path.commonpath([base, target]) != base:
                self.send_error(403, "Access denied")
                return
            if not os.path.isdir(target):
                self.send_error(404, "Directory not found")
                return
            folders = []
            with os.scandir(target) as entries:
                for entry in entries:
                    if entry.name.casefold() == STATE_FOLDER:
                        continue
                    if not entry.is_dir():
                        continue
                    resolved = os.path.realpath(entry.path)
                    if os.path.commonpath([base, resolved]) != base:
                        continue
                    path = '/' + '/'.join(filter(None, [relative.replace(os.sep, '/').rstrip('/'), entry.name])) + '/'
                    folders.append({'name': entry.name, 'path': path})
            folders.sort(key=lambda folder: folder['name'].casefold())
            content = json.dumps({'folders': folders}, ensure_ascii=False).encode('utf-8')
        except ValueError:
            self.send_error(403, "Access denied")
            return
        except OSError:
            self.send_error(403, "Cannot list directory")
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, data, cache_control=None):
        content = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        if cache_control:
            self.send_header('Cache-Control', cache_control)
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        config = self.config
        if not self.check_security(): return
        if self.serve_temporary_link(): return
        if self.handle_redirections(): return
        if not self.authorize_request(): return

        if self.path in ('/api/restore', '/api/undo-move'):
            if not config.get('allow_mod'):
                self.send_error(405, 'Modification not allowed')
                return
            try:
                data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
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
                content_length = int(self.headers.get('Content-Length', 0))
                data = json.loads(self.rfile.read(content_length))
                
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
            except FileExistsError:
                self.send_error(409, 'Destination already exists')
            except ExplorerError as e:
                self.send_error(e.status, str(e))
            except Exception as e:
                self.send_error(500, str(e))
                return
        
        # Intent execution API
        if config.get('enable_intents') and self.path == '/api/intent':
            length = int(self.headers.get('Content-Length', 0))
            data = self.rfile.read(length).decode('utf-8')
            try:
                payload = json.loads(data)
                command = payload.get('command')
                if command:
                    result = subprocess.run(command, shell=True, capture_output=True, text=True)
                    response = {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
                    response_bytes = json.dumps(response).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(response_bytes)))
                    self.end_headers()
                    self.wfile.write(response_bytes)
                    return
                else:
                    self.send_error(400, "Missing 'command' in JSON")
                    return
            except Exception as e:
                self.send_error(500, f"Error executing intent: {e}")
                return

        self.send_error(405, "Method Not Allowed")

    def check_auth(self):
        auth_header = self.headers.get('Authorization')
        if not auth_header:
            self.send_auth_request()
            return False
        
        config = self.config
        auth_credentials = config.get('auth_credentials')
        try:
            auth_type, auth_token = auth_header.split(' ', 1)
            if auth_type.lower() == 'basic':
                import base64
                decoded = base64.b64decode(auth_token).decode('utf-8')
                user, pwd = decoded.split(':', 1)
                if user == auth_credentials[0] and pwd == auth_credentials[1]:
                    return True
        except Exception:
            pass

        self.send_auth_request()
        return False

    def send_auth_request(self):
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="HTTP Server Manager"')
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"401 Unauthorized")

    def log_request(self, code='-', size='-'):
        if self.is_link_request():
            self.log_message('"%s %s %s" %s %s', self.command, DOWNLOAD_PREFIX + '[link]', self.request_version, str(code), str(size))
        else:
            super().log_request(code, size)

    def log_message(self, format, *args):
        try:
            msg = format % args
        except Exception:
            msg = " ".join([str(format)] + [str(a) for a in args])
        client = self.client_ip if hasattr(self, 'client_address') and self.client_address else "unknown"
        print(f"{client} - - [{self.log_date_time_string()}] {redact_download_tokens(msg)}")
