import base64
import http.client
import os
from pathlib import Path
import tempfile
import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QObject, Signal, QSettings, QSize
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication, QWidget, QComboBox
from src.core.camera import CameraFeed
from src.core.server import ServerManager
from src.gui import camera as camera_gui
from src.gui.i18n import InterfaceLanguage


class TestCameraFeed(unittest.TestCase):
    def test_published_rate_frame_identity_and_reset(self):
        now = [0]
        feed = CameraFeed(clock=lambda: now[0])
        token = feed.start()
        jpeg = b'\xff\xd8image\xff\xd9'
        feed.publish(token, jpeg, size=(640, 360))
        first = feed.snapshot_details()['frame_id']
        for timestamp in (.2, .4, .6, .8, 1):
            now[0] = timestamp
            feed.publish(token, jpeg, size=(640, 360))
        self.assertAlmostEqual(feed.stats()['published_fps'], 5)
        self.assertEqual(feed.stats()['width'], 640)
        details = feed.snapshot_details()
        self.assertNotEqual(details['frame_id'], first)
        # Reading the same frame does not count as another published frame.
        for _ in range(20):
            self.assertEqual(feed.snapshot_details()['frame_id'], details['frame_id'])
        self.assertAlmostEqual(feed.stats()['published_fps'], 5)
        now[0] = 5
        self.assertEqual(feed.stats()['published_fps'], 0)
        self.assertIsNone(feed.snapshot_details())
        feed.stop()
        self.assertEqual(feed.stats()['width'], 0)
        new_token = feed.start()
        feed.publish(new_token, jpeg)
        self.assertNotEqual(feed.snapshot_details()['frame_id'], first)
        self.assertEqual(feed.stats()['published_fps'], 0)

    def test_fps_limits_and_preservation_across_sessions(self):
        feed = CameraFeed()
        self.assertEqual(feed.fps, 5)
        for value in (0, 31, -1, 5.5, True, '10', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                feed.set_fps(value)
        for value in (1, 15, 30):
            feed.set_fps(value)
            feed.start()
            feed.stop()
            self.assertEqual(feed.fps, value)

    def test_sessions_expiry_bounds_and_late_callbacks(self):
        now = [10]
        feed = CameraFeed(clock=lambda: now[0])
        self.assertIsNone(feed.snapshot())
        first = feed.start()
        self.assertFalse(feed.publish(first, b'not JPEG'))
        self.assertFalse(feed.publish(first, b'\xff\xd8' + b'0' * feed.MAX_BYTES + b'\xff\xd9'))
        self.assertTrue(feed.publish(first, b'\xff\xd8first\xff\xd9'))
        self.assertEqual(feed.snapshot(), b'\xff\xd8first\xff\xd9')
        now[0] = 14
        self.assertIsNone(feed.snapshot())
        second = feed.start()
        self.assertFalse(feed.publish(first, b'\xff\xd8late\xff\xd9'))
        feed.stop(first)
        self.assertTrue(feed.is_current(second))
        self.assertTrue(feed.publish(second, b'\xff\xd8second\xff\xd9'))
        feed.stop()
        self.assertIsNone(feed.snapshot())
        self.assertFalse(feed.publish(second, b'\xff\xd8late\xff\xd9'))

    def test_audio_feed_validation_ring_limit_and_expiry(self):
        now = [10]
        audio = CameraFeed(clock=lambda: now[0]).audio
        with self.assertRaises(ValueError):
            audio.start(12345, 1)
        session = audio.start(8000, 1)
        self.assertFalse(audio.publish(session, b'\x00'))
        self.assertFalse(audio.publish('other', b'\x00\x00'))
        for _ in range(8):
            self.assertTrue(audio.publish(session, b'\x00\x00' * 8000))
        self.assertLessEqual(audio.end_offset - audio.start_offset, 8000 * 2 * audio.MAX_SECONDS)
        _, end, _, _, data = audio.read()
        self.assertEqual(len(data), 8000)
        now[0] = 14
        self.assertIsNone(audio.read())
        audio.stop()
        self.assertIsNone(audio.read())


class TestCameraHTTP(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.server = ServerManager()
        ok, message = self.server.start_server('127.0.0.1', 0, self.scratch.name,
            auth_credentials=('reader', 'secret'), render_pages=True,
            custom_headers={'Cache-Control': 'public, max-age=9999', 'Content-Security-Policy': "default-src *"},
            cors_config={'origin': '*'}, shared_folders=[{'name': 'extra', 'path': self.scratch.name, 'writable': False}])
        self.assertTrue(ok, message)
        self.addCleanup(self.scratch.cleanup)
        self.addCleanup(self.server.stop_server)
        self.port = self.server.httpd.server_address[1]
        self.auth = {'Authorization': 'Basic ' + base64.b64encode(b'reader:secret').decode()}

    def request(self, path, method='GET', auth=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            connection.request(method, path, headers=self.auth if auth else {})
            response = connection.getresponse()
            return response.status, response.headers, response.read()
        finally:
            connection.close()

    def test_authentication_headers_and_disabled_frame(self):
        for path in ('/_camera/', '/_camera/viewer.js', '/_camera/viewer.css', '/_camera/frame.jpg'):
            status, headers, body = self.request(path, auth=False)
            self.assertEqual(status, 401)
            self.assertIn('no-store', headers['Cache-Control'])
        for path, marker in [('/_camera/', b'<html'), ('/_camera/viewer.js', b'fetch('), ('/_camera/viewer.css', b'.preview')]:
            status, headers, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn(marker, body)
            self.assertIn('no-store', headers['Cache-Control'])
            self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
            self.assertEqual(headers['Cross-Origin-Resource-Policy'], 'same-origin')
            self.assertIsNone(headers.get('Access-Control-Allow-Origin'))
        status, headers, body = self.request('/_camera/frame.jpg')
        self.assertEqual(status, 503)
        self.assertEqual(body, b'')
        self.assertEqual(headers['Retry-After'], '1')

    def test_head_frame_stop_and_no_mount_alias(self):
        token = self.server.camera.start()
        jpeg = b'\xff\xd8test frame\xff\xd9'
        self.server.camera.publish(token, jpeg)
        status, headers, body = self.request('/_camera/frame.jpg?t=1')
        self.assertEqual((status, body), (200, jpeg))
        self.assertEqual(headers['Content-Type'], 'image/jpeg')
        status, headers, body = self.request('/_camera/frame.jpg', 'HEAD')
        self.assertEqual(status, 200)
        self.assertEqual(int(headers['Content-Length']), len(jpeg))
        self.assertEqual(body, b'')
        self.assertEqual(self.request('/_camera/unknown')[0], 404)
        self.assertEqual(self.request('/_camera')[0], 302)
        self.assertEqual(self.request('/_shares/extra/_camera/frame.jpg')[0], 404)
        self.server.camera.stop()
        self.assertEqual(self.request('/_camera/frame.jpg')[0], 503)
        token = self.server.camera.start()
        self.server.camera.publish(token, jpeg)
        self.server.stop_server()
        self.assertIsNone(self.server.camera.snapshot())
        self.assertFalse(self.server.camera.publish(token, jpeg))

    def test_fps_header_tracks_live_changes_and_ignores_custom_override(self):
        self.server.httpd.app_config['custom_headers']['X-Camera-FPS'] = '99'
        self.assertEqual(self.request('/_camera/frame.jpg')[1]['X-Camera-FPS'], '5')
        token = self.server.camera.start()
        self.server.camera.publish(token, b'\xff\xd8test\xff\xd9')
        for value in (1, 20, 30):
            self.server.camera.set_fps(value)
            status, headers, _ = self.request('/_camera/frame.jpg')
            self.assertEqual(status, 200)
            self.assertEqual(headers.get_all('X-Camera-FPS'), [str(value)])
            self.assertTrue(self.server.camera.is_current(token))

    def test_frame_metadata_is_stable_and_custom_headers_cannot_override_it(self):
        self.server.httpd.app_config['custom_headers'].update({'X-Camera-Frame-ID': 'fake', 'X-Camera-Published-FPS': '99'})
        token = self.server.camera.start()
        self.server.camera.publish(token, b'\xff\xd8frame\xff\xd9', size=(320, 240))
        first = self.request('/_camera/frame.jpg')[1]
        self.assertNotEqual(first['X-Camera-Frame-ID'], 'fake')
        self.assertEqual(first.get_all('X-Camera-Published-FPS'), ['0.00'])
        self.assertEqual(self.request('/_camera/frame.jpg')[1]['X-Camera-Frame-ID'], first['X-Camera-Frame-ID'])
        self.server.camera.publish(token, b'\xff\xd8next\xff\xd9')
        self.assertNotEqual(self.request('/_camera/frame.jpg')[1]['X-Camera-Frame-ID'], first['X-Camera-Frame-ID'])

    def test_audio_requires_auth_is_unavailable_until_started_and_streams_by_offset(self):
        self.assertEqual(self.request('/_camera/audio.pcm', auth=False)[0], 401)
        status, headers, body = self.request('/_camera/audio.pcm')
        self.assertEqual((status, body), (503, b''))
        self.assertEqual(self.request('/_camera/frame.jpg')[1]['X-Camera-Audio'], '0')
        session = self.server.camera.audio.start(16000, 1)
        self.assertEqual(self.request('/_camera/frame.jpg')[1]['X-Camera-Audio'], '1')
        self.assertTrue(self.server.camera.audio.publish(session, b'\x01\x00' * 800))
        status, headers, body = self.request('/_camera/audio.pcm')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'application/octet-stream')
        self.assertEqual((headers['X-Audio-Rate'], headers['X-Audio-Channels']), ('16000', '1'))
        self.assertEqual(len(body), 1600)
        offset = headers['X-Audio-Offset']
        self.server.camera.audio.publish(session, b'\x02\x00' * 100)
        status, headers, body = self.request('/_camera/audio.pcm?session=%s&after=%s' % (headers['X-Audio-Session'], offset))
        self.assertEqual(body, b'\x02\x00' * 100)
        self.server.camera.stop()
        self.assertEqual(self.request('/_camera/audio.pcm')[0], 503)

    def test_ip_and_rate_limit_still_apply(self):
        self.server.httpd.app_config['whitelist'] = ['192.0.2.1']
        self.assertEqual(self.request('/_camera/frame.jpg')[0], 403)
        self.server.httpd.app_config['whitelist'] = []
        self.server.httpd.app_config['rate_limit'] = 1
        self.assertEqual(self.request('/_camera/')[0], 200)
        self.assertEqual(self.request('/_camera/frame.jpg')[0], 429)


DEVICE = SimpleNamespace(id=lambda: b'demo-device', description=lambda: 'Camera (simulated)')


class FakeDevices(QObject):
    videoInputsChanged = Signal()

    @staticmethod
    def videoInputs():
        return [DEVICE]


class FakeCamera(QObject):
    errorOccurred = Signal(object, str)
    activeChanged = Signal(bool)

    def __init__(self, device, parent):
        super().__init__(parent)
        self.stopped = False

    def start(self):
        self.activeChanged.emit(True)

    def stop(self):
        self.stopped = True
        self.activeChanged.emit(False)

    def setCameraFormat(self, format):
        self.format = format


class FakeCapture(QObject):
    def setCamera(self, camera):
        self.camera = camera

    def setVideoSink(self, sink):
        self.sink = sink


class FakeSink(QObject):
    videoFrameChanged = Signal(object)


class TestAudioLevel(unittest.TestCase):
    def test_silence_full_scale_and_quiet_levels(self):
        self.assertEqual(camera_gui.audio_level(b''), 0)
        self.assertEqual(camera_gui.audio_level(bytes(200)), 0)
        loud = (-32768).to_bytes(2, 'little', signed=True) * 10
        self.assertEqual(camera_gui.audio_level(loud), 100)
        half = (16384).to_bytes(2, 'little', signed=True) * 10
        self.assertTrue(80 <= camera_gui.audio_level(half) < 100)
        quiet = (10).to_bytes(2, 'little', signed=True) * 10
        self.assertLess(camera_gui.audio_level(quiet), camera_gui.audio_level(half))


class TestCameraPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        for name, value in [('QMediaDevices', FakeDevices), ('QCamera', FakeCamera), ('QMediaCaptureSession', FakeCapture), ('QVideoSink', FakeSink)]:
            patcher = patch.object(camera_gui, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = QWidget()
        self.combo = QComboBox()
        self.combo.addItem('LAN', 'http://192.168.1.8:8080/')
        self.controller = SimpleNamespace(language=InterfaceLanguage('pt'), window=self.window, access_combo=self.combo,
            server_manager=SimpleNamespace(is_running=False, camera=CameraFeed()))
        self.panel = camera_gui.CameraPanel(self.controller)
        self.addCleanup(self.window.close)
        self.addCleanup(self.panel.close)
        self.addCleanup(self.panel.stop)

    def start_panel(self):
        self.panel.refresh()
        self.assertFalse(self.panel.start_button.isEnabled())
        self.controller.server_manager.is_running = True
        self.panel.update_actions()
        self.panel.start()

    def test_start_frame_throttle_translation_and_server_stop(self):
        with patch.object(camera_gui.time, 'monotonic', return_value=100):
            self.start_panel()
            token = self.panel.session
            camera = self.panel.camera
            self.assertIsNotNone(token)
            self.assertFalse(self.panel.devices.isEnabled())
            self.assertTrue(self.panel.stop_button.isEnabled())
            image = QImage(1600, 1200, QImage.Format_RGB32)
            image.fill(QColor('red'))
            frame = SimpleNamespace(toImage=lambda: image)
            self.panel.sink.videoFrameChanged.emit(frame)
            jpeg = self.panel.feed.snapshot()
            self.assertIsNotNone(jpeg)
            decoded = QImage.fromData(jpeg)
            self.assertEqual((decoded.width(), decoded.height()), (720, 540))
            self.assertEqual(self.panel.url.text(), 'http://192.168.1.8:8080/_camera/')
            self.panel.controller.language.code = 'en'
            self.panel.retranslate()
            self.assertEqual(self.panel.stop_button.text(), 'Stop streaming')
            self.assertIn('Camera live', self.panel.status.text())
        with patch.object(camera_gui.time, 'monotonic', return_value=100.1), patch.object(self.panel.feed, 'publish') as publish:
            self.panel.on_frame(frame, token)
            publish.assert_not_called()
        self.controller.server_manager.camera.stop()
        self.controller.server_manager.is_running = False
        self.panel.update_actions()
        self.assertTrue(camera.stopped)
        self.assertIsNone(self.panel.session)
        self.assertIsNone(self.panel.feed.snapshot())
        self.assertFalse(self.panel.open_button.isEnabled())
        self.panel.on_frame(frame, token)
        self.assertIsNone(self.panel.feed.snapshot())

    def test_camera_error_disconnect_timeout_and_window_close(self):
        self.start_panel()
        camera = self.panel.camera
        camera.errorOccurred.emit(1, 'Permission denied')
        self.assertIsNone(self.panel.session)
        self.assertIn('Permission denied', self.panel.status.text())
        self.assertTrue(camera.stopped)
        self.panel.start()
        with patch.object(camera_gui.time, 'monotonic', return_value=self.panel.started + 11):
            self.panel.check_capture()
        self.assertIsNone(self.panel.session)
        self.assertIn('Nenhuma imagem', self.panel.status.text())
        self.panel.start()
        with patch.object(FakeDevices, 'videoInputs', return_value=[]):
            self.panel.devices_changed()
        self.assertIsNone(self.panel.session)
        self.assertIn('desconectada', self.panel.status.text())
        self.panel.start()
        self.window.close()
        self.assertIsNone(self.panel.session)

    def test_fps_changes_capture_rate_without_restarting(self):
        image = QImage(32, 24, QImage.Format_RGB32)
        image.fill(QColor('blue'))
        frame = SimpleNamespace(toImage=lambda: image)
        with patch.object(camera_gui.time, 'monotonic', return_value=100):
            self.start_panel()
            self.panel.on_frame(frame, self.panel.session)
        token, camera = self.panel.session, self.panel.camera
        self.panel.fps.setValue(20)
        self.assertEqual(self.panel.feed.fps, 20)
        with patch.object(camera_gui.time, 'monotonic', return_value=100.04), patch.object(self.panel.feed, 'publish', wraps=self.panel.feed.publish) as publish:
            self.panel.on_frame(frame, token)
            publish.assert_not_called()
        with patch.object(camera_gui.time, 'monotonic', return_value=100.06), patch.object(self.panel.feed, 'publish', wraps=self.panel.feed.publish) as publish:
            self.panel.on_frame(frame, token)
            publish.assert_called_once()
        self.assertIn('20 quadros', self.panel.status.text())
        self.panel.fps.setValue(1)
        with patch.object(camera_gui.time, 'monotonic', return_value=100.5), patch.object(self.panel.feed, 'publish') as publish:
            self.panel.on_frame(frame, token)
            publish.assert_not_called()
        self.assertIs(self.panel.camera, camera)
        self.assertEqual(self.panel.session, token)
        self.assertFalse(camera.stopped)

    def test_fps_preference_restore_and_language_change(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / 'camera.ini'), QSettings.IniFormat)
            self.controller.settings = settings
            settings.setValue('camera/fps', 15)
            settings.setValue('camera/quality', 85)
            settings.setValue('camera/resolution_width', 1280)
            panel = camera_gui.CameraPanel(self.controller)
            try:
                self.assertEqual(panel.fps.value(), 15)
                self.assertEqual(panel.quality.value(), 85)
                self.assertEqual(panel.resolution.currentData(), (1280, 720))
                panel.quality.setValue(45)
                panel.resolution.setCurrentIndex(1)
                self.assertEqual(int(settings.value('camera/quality')), 45)
                self.assertEqual(int(settings.value('camera/resolution_width')), 640)
                panel.fps.setValue(24)
                self.assertEqual(int(settings.value('camera/fps')), 24)
                self.controller.language.code = 'en'
                panel.retranslate()
                self.assertEqual(panel.fps_label.text(), 'Transmission frame rate:')
                self.assertEqual(panel.fps.value(), 24)
            finally:
                panel.close()
            settings.setValue('camera/fps', 'invalid')
            settings.setValue('camera/quality', 999)
            settings.setValue('camera/resolution_width', 999)
            restored = camera_gui.CameraPanel(self.controller)
            try:
                self.assertEqual(restored.fps.value(), 5)
                self.assertEqual(restored.quality.value(), 75)
                self.assertEqual(restored.resolution.currentData(), (960, 540))
            finally:
                restored.close()

    def test_resolution_quality_and_no_upscaling_during_capture(self):
        self.start_panel()
        token = self.panel.session
        raw = random.Random(42).randbytes(1280 * 720 * 3)
        image = QImage(raw, 1280, 720, 1280 * 3, QImage.Format_RGB888).copy()
        frame = SimpleNamespace(toImage=lambda: image)
        self.panel.resolution.setCurrentIndex(1)  # 640 x 480 maximum; 16:9 input.
        self.panel.quality.setValue(10)
        self.panel.on_frame(frame, token)
        small = self.panel.feed.snapshot()
        self.assertEqual(QImage.fromData(small).size(), QSize(640, 360))
        self.panel.quality.setValue(95)
        with patch.object(camera_gui.time, 'monotonic', return_value=self.panel.last_frame + .3):
            self.panel.on_frame(frame, token)
        self.assertGreater(len(self.panel.feed.snapshot()), len(small))
        self.panel.resolution.setCurrentIndex(4)
        with patch.object(camera_gui.time, 'monotonic', return_value=self.panel.last_frame + .3):
            self.panel.on_frame(frame, token)
        self.assertEqual(QImage.fromData(self.panel.feed.snapshot()).size(), QSize(1280, 720))
        self.assertIn('1280 × 720', self.panel.metrics.text())
        self.assertEqual(self.panel.session, token)

    def test_capture_uses_only_advertised_formats(self):
        def format(width, height, fps):
            return SimpleNamespace(resolution=lambda: QSize(width, height), maxFrameRate=lambda: fps)
        low = format(640, 480, 30)
        medium_slow, medium_fast = format(1280, 720, 15), format(1280, 720, 30)
        high = format(1920, 1080, 15)
        with patch.object(DEVICE, 'videoFormats', return_value=[low, medium_slow, medium_fast, high], create=True):
            self.assertIs(camera_gui.choose_camera_format(DEVICE, (960, 540), 30), medium_fast)
            self.start_panel()
            self.assertIs(self.panel.camera.format, medium_fast)
            self.panel.resolution.setCurrentIndex(4)
            self.assertIs(self.panel.camera.format, high)
        self.assertIsNone(camera_gui.choose_camera_format(DEVICE, (960, 540), 5))

    def test_empty_discovery_and_no_automatic_start(self):
        with patch.object(FakeDevices, 'videoInputs', return_value=[]):
            self.panel.refresh()
        self.assertEqual(self.panel.devices.count(), 0)
        self.assertFalse(self.panel.start_button.isEnabled())
        self.assertIn('Nenhuma câmera', self.panel.status.text())
        self.controller.server_manager.is_running = True
        self.panel.start()
        self.assertIsNone(self.panel.session)
