"""Exercise Qt/controller/HTTP together using temporary files and INI settings."""

import base64
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings, QThreadPool
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from src.core.access import hash_password
from src.gui.controller import AppController


def main():
    output = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path('artifacts/desktop-smoke').resolve()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    # The offscreen plugin does not load Windows system fonts automatically.
    if Path('C:/Windows/Fonts/segoeui.ttf').is_file():
        font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
        if font_id >= 0:
            app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
    assert QFontMetrics(app.font()).inFont('A'), 'No usable font for visual validation'
    results = []
    with tempfile.TemporaryDirectory(prefix='serverpy_desktop_') as scratch:
        folder = Path(scratch) / 'files'
        folder.mkdir()
        (folder / 'sample.txt').write_text('original', encoding='utf-8')
        settings = QSettings(str(Path(scratch) / 'settings.ini'), QSettings.IniFormat)
        settings.setValue('interface_language', 'pt')
        streams = sys.stdout, sys.stderr
        controller = None
        try:
            with patch('src.gui.controller.QSettings', return_value=settings):
                controller = AppController()
            sys.stdout, sys.stderr = streams
            controller.window.line_root_folder.setText(str(folder))
            controller.window.line_port.setText('0')
            combo = controller.window.combo_interface
            index = next(index for index in range(combo.count()) if combo.itemText(index).split()[0] == '127.0.0.1')
            combo.setCurrentIndex(index)
            controller.window.chk_auth.setChecked(True)
            controller.window.line_username.setText('smoke-admin')
            controller.window.line_password.setText('temporary-admin-secret')
            controller.window.chk_allow_mod.setChecked(True)
            controller.window.chk_render_pages.setChecked(True)
            controller.folder_users_enabled = True
            controller.folder_users = [dict(name='reader', password=hash_password('temporary-reader-secret'),
                                            grants={'/': ['view', 'download']})]
            controller.window.show()
            QTest.qWait(100)
            for size in ((980, 760), (1440, 900)):
                controller.window.resize(*size)
                for index, title in enumerate(controller.navigation.TAB_TITLES):
                    controller.navigation.tabs.setCurrentIndex(index)
                    QTest.qWait(30)
                    image = controller.window.grab()
                    assert not image.isNull(), title
                    assert image.save(str(output / f'{size[0]}-{title.lower().replace(" ", "-")}.png'))
            results.append('All 11 Qt tabs rendered at 980x760 and 1440x900 (offscreen).')
            controller.navigation.tabs.setCurrentIndex(0)
            controller._start_server()
            assert controller.server_manager.is_running, 'Controller failed to start server'
            port = controller.server_manager.httpd.server_address[1]

            def request(path, method='GET', body=None, account='admin'):
                headers = {}
                if account:
                    credentials = 'smoke-admin:temporary-admin-secret' if account == 'admin' else 'reader:temporary-reader-secret'
                    headers['Authorization'] = 'Basic ' + base64.b64encode(credentials.encode()).decode()
                if isinstance(body, dict):
                    body = json.dumps(body).encode()
                    headers['Content-Type'] = 'application/json'
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                try:
                    connection.request(method, path, body, headers)
                    response = connection.getresponse()
                    return response.status, response.read()
                finally:
                    connection.close()

            assert request('/', account=None)[0] == 401
            assert request('/sample.txt', account='reader') == (200, b'original')
            assert request('/sample.txt', 'PUT', b'forbidden', account='reader')[0] == 403
            assert request('/api/intent', 'POST', {'command': 'ignored'}, account='reader')[0] == 403
            assert (folder / 'sample.txt').read_bytes() == b'original'
            results.append('Controller started loopback HTTP; authentication and reader permission boundary passed.')
            assert request('/uploaded.txt', 'PUT', b'uploaded bytes')[0] == 201
            assert request('/uploaded.txt')[1] == b'uploaded bytes'
            assert request('/uploaded.txt', 'DELETE')[0] == 204
            status, body = request('/api/trash')
            assert status == 200
            item = next(item for item in json.loads(body)['items'] if item['name'] == 'uploaded.txt')
            assert request('/api/restore', 'POST', {'id': item['id']})[0] == 200
            assert request('/uploaded.txt')[1] == b'uploaded bytes'
            results.append('Real HTTP upload/download/delete/restore passed using scratch files.')
            controller._stop_server()
            assert not controller.server_manager.is_running
            controller._start_server()
            assert controller.server_manager.is_running
            controller._stop_server()
            controller.save_server_preferences()
            settings.sync()
            persisted = Path(scratch, 'settings.ini').read_text(encoding='utf-8')
            assert 'temporary-admin-secret' not in persisted
            assert 'temporary-reader-secret' not in persisted
            results.append('Controller stop/restart passed; no plaintext test passwords in isolated INI settings.')
        finally:
            sys.stdout, sys.stderr = streams
            if controller is not None:
                controller.server_manager.stop_server()
                controller.schedule_timer.stop()
                # Visiting device tabs can start real read-only discovery tasks.
                # Deliver their queued signals before destroying Qt objects.
                deadline = time.monotonic() + 30
                pool = QThreadPool.globalInstance()
                while True:
                    app.processEvents()
                    if (not pool.activeThreadCount() and not controller.navigation.android.loading
                            and not controller.navigation.storage.loading):
                        break
                    assert time.monotonic() < deadline, 'Device discovery did not finish'
                    QTest.qWait(50)
                assert pool.waitForDone(1000), 'Device discovery did not finish'
                app.processEvents()
                controller.window.close()
                controller.log_window.close()
                app.processEvents()
    (output / 'results.json').write_text(json.dumps(dict(mode='automated Qt offscreen; not a manual hardware test',
                                                       checks=results), indent=2), encoding='utf-8')
    for result in results:
        print(result)


if __name__ == '__main__':
    main()
