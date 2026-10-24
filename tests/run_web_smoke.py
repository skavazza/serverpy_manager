"""Run the web smoke checks with Node and an isolated, headless Chrome profile."""

import base64
import os
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.server import ServerManager


def main():
    chrome_path = shutil.which('chrome') or shutil.which('google-chrome') or shutil.which('chromium')
    if not chrome_path or not shutil.which('node'):
        raise SystemExit('Chrome and Node are required for these browser checks.')
    with tempfile.TemporaryDirectory(prefix='serverpy_browser_') as scratch:
        root = Path(scratch) / 'files'
        (root / 'docs' / 'nested').mkdir(parents=True)
        (root / 'empty').mkdir()
        (root / 'sample.txt').write_text('sample')
        (root / 'link-only.txt').write_text('temporary link download')
        (root / 'large.txt').write_text('x' * 2000)
        (root / 'docs' / 'nested' / 'deep-report.txt').write_text('nested search result')
        (root / 'image.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aGZkAAAAASUVORK5CYII='))
        # These fixtures check player/frame creation, not codec support or PDF rendering.
        (root / 'video.mp4').write_bytes(b'fixture')
        (root / 'document.pdf').write_bytes(b'%PDF-1.4\n%%EOF')
        with wave.open(str(root / 'sound.wav'), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b'\0\0' * 800)
        server = ServerManager()
        readonly = ServerManager()
        mounted = os.environ.get('SERVERPY_SMOKE_MOUNT') == '1'
        main_root = root.parent / 'main' if mounted else root
        main_root.mkdir(exist_ok=True)
        options = {'shared_folders': [{'name': 'files', 'path': str(root), 'writable': True}]} if mounted else {}
        suffix = '/_shares/files/' if mounted else '/'
        success, message = server.start_server('127.0.0.1', 0, str(main_root), render_pages=True, allow_mod=True, **options)
        if not success:
            raise RuntimeError(message)
        success, message = readonly.start_server('127.0.0.1', 0, str(main_root), render_pages=True, allow_mod=False, **options)
        if not success:
            server.stop_server()
            raise RuntimeError(message)
        profile = Path(scratch) / 'chrome'
        browser = None
        try:
            browser = subprocess.Popen(
                [chrome_path, '--headless', '--disable-gpu', '--no-first-run', '--remote-debugging-port=0', '--user-data-dir=' + str(profile), 'about:blank'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            port_file = profile / 'DevToolsActivePort'
            for _ in range(100):
                if port_file.exists():
                    break
                time.sleep(0.1)
            port = port_file.read_text().splitlines()[0]
            script = Path(__file__).with_name('web_interface_smoke.cjs')
            url = 'http://127.0.0.1:' + str(server.httpd.server_address[1]) + suffix
            args = ['node', str(script), port, url]
            args.append(str(Path(sys.argv[1]).resolve()) if len(sys.argv) > 1 else '')
            args.append('http://127.0.0.1:' + str(readonly.httpd.server_address[1]) + suffix)
            signals = Path(scratch) / 'signals'
            signals.mkdir()
            args.append(str(signals))
            explorer = server.httpd.shared_explorers['files'] if mounted else server.httpd.explorer
            plain_token = server.links.create(explorer, root / 'link-only.txt')
            protected_token = server.links.create(explorer, root / 'link-only.txt', password='download-password')
            origin = 'http://127.0.0.1:' + str(server.httpd.server_address[1])
            link_fixture = Path(scratch) / 'links.json'
            link_fixture.write_text(json.dumps({
                'plain': origin + '/_download/' + plain_token,
                'protected': origin + '/_download/' + protected_token,
                'password': 'download-password', 'directory': str(Path(scratch) / 'downloads'),
            }), encoding='utf-8')
            args.append(str(link_fixture))
            server_port = server.httpd.server_address[1]
            stopped = threading.Event()
            errors = []

            def toggle_server():
                try:
                    while not stopped.wait(0.05):
                        if (signals / 'stop').exists() and not (signals / 'stopped').exists():
                            server.stop_server()
                            (signals / 'stopped').touch()
                        if (signals / 'start').exists() and not (signals / 'started').exists():
                            ok, message = server.start_server('127.0.0.1', server_port, str(main_root), render_pages=True, allow_mod=True, **options)
                            if not ok:
                                raise RuntimeError(message)
                            (signals / 'started').touch()
                except Exception as error:
                    errors.append(error)

            toggler = threading.Thread(target=toggle_server, daemon=True)
            toggler.start()
            try:
                subprocess.run(args, check=True, timeout=60)
                if errors:
                    raise errors[0]
            finally:
                stopped.set()
                toggler.join(timeout=5)
        finally:
            server.stop_server()
            readonly.stop_server()
            if browser:
                if browser.poll() is None:
                    browser.terminate()
                browser.wait(timeout=10)


if __name__ == '__main__':
    main()
