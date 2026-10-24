"""Chrome camera-viewer checks with generated frames; never opens camera hardware."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QColor, QPainter, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from src.core.server import ServerManager


def main():
    chrome = shutil.which('chrome') or shutil.which('google-chrome') or shutil.which('chromium')
    if not chrome or not shutil.which('node'):
        raise SystemExit('Chrome and Node are required.')
    app = QApplication.instance() or QApplication([])
    if Path('C:/Windows/Fonts/segoeui.ttf').is_file():
        font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
        if font_id >= 0:
            app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 14))
    image = QImage(800, 450, QImage.Format_RGB32)
    image.fill(QColor('#20465e'))
    painter = QPainter(image)
    painter.setPen(QColor('white'))
    painter.setFont(app.font())
    painter.drawText(image.rect(), 0x84, 'CAMERA SIMULADA / SYNTHETIC CAMERA')
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, 'JPEG', 80)
    jpeg = bytes(buffer.data())
    smaller = image.scaled(320, 180)
    small_buffer = QBuffer()
    small_buffer.open(QIODevice.WriteOnly)
    smaller.save(small_buffer, 'JPEG', 40)
    small_jpeg = bytes(small_buffer.data())
    with tempfile.TemporaryDirectory(prefix='serverpy_camera_smoke_') as scratch:
        root = Path(scratch)
        signals = root / 'signals'
        signals.mkdir()
        server = ServerManager()
        ok, message = server.start_server('127.0.0.1', 0, scratch, render_pages=True,
            auth_credentials=('camera-reader', 'smoke-password'))
        if not ok:
            raise RuntimeError(message)
        stopped = threading.Event()
        token = server.camera.start()

        def publish():
            session = token
            off = False
            while not stopped.wait(.1):
                if (signals / 'fps').exists():
                    try:
                        server.camera.set_fps(int((signals / 'fps').read_text()))
                    except (ValueError, OSError):
                        pass  # The test process may still be writing the signal file.
                if (signals / 'off').exists() and not off:
                    server.camera.stop()
                    off = True
                    session = None
                if (signals / 'on').exists() and session is None:
                    session = server.camera.start()
                if session:
                    small = (signals / 'small').exists()
                    server.camera.publish(session, small_jpeg if small else jpeg,
                        size=(320, 180) if small else (800, 450))

        producer = threading.Thread(target=publish, daemon=True)
        producer.start()
        browser = None
        try:
            profile = root / 'chrome'
            browser = subprocess.Popen([chrome, '--headless', '--disable-gpu', '--no-first-run',
                '--remote-debugging-port=0', '--user-data-dir=' + str(profile), 'about:blank'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            port_file = profile / 'DevToolsActivePort'
            for _ in range(100):
                if port_file.exists():
                    break
                time.sleep(.1)
            port = port_file.read_text().splitlines()[0]
            url = 'http://127.0.0.1:' + str(server.httpd.server_address[1]) + '/_camera/'
            subprocess.run(['node', str(Path(__file__).with_name('camera_smoke.cjs')), port, url,
                str(signals), str(Path('artifacts/camera').resolve())], check=True, timeout=45)
        finally:
            stopped.set()
            producer.join(timeout=2)
            server.stop_server()
            if browser:
                try:
                    browser.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    browser.terminate()
                    try:
                        browser.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        browser.kill()
                        browser.wait(timeout=5)


if __name__ == '__main__':
    main()
