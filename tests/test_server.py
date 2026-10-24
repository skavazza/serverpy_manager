import unittest
import os
import shutil
import tempfile
import urllib.request
import urllib.error
import urllib.parse
import json
import time
import base64
from src.core.server import ServerManager

class TestServerCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="serverpy_test_")
        cls.sample_file = os.path.join(cls.test_dir, "sample.txt")
        with open(cls.sample_file, "w", encoding="utf-8") as f:
            f.write("Hello ServerPy Test")

        cls.sub_dir = os.path.join(cls.test_dir, "subfolder")
        os.makedirs(cls.sub_dir, exist_ok=True)
        with open(os.path.join(cls.sub_dir, "subfile.txt"), "w", encoding="utf-8") as f:
            f.write("Sub content")

        cls.server_manager = ServerManager()
        cls.port = 18888
        cls.host = "127.0.0.1"
        cls.auth_user = "admin"
        cls.auth_pass = "secret123"

        started, msg = cls.server_manager.start_server(
            cls.host,
            cls.port,
            cls.test_dir,
            allow_mod=True,
            render_pages=True,
            auth_credentials=(cls.auth_user, cls.auth_pass),
            rate_limit=100
        )
        assert started, f"Could not start server: {msg}"
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.server_manager.stop_server()
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def _auth_headers(self):
        token = base64.b64encode(f"{self.auth_user}:{self.auth_pass}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def test_auth_required_for_read_api(self):
        url = f"http://{self.host}:{self.port}/api/read?path=sample.txt"
        req = urllib.request.Request(url)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 401)

    def test_auth_success_and_read(self):
        url = f"http://{self.host}:{self.port}/api/read?path=sample.txt"
        req = urllib.request.Request(url, headers=self._auth_headers())
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = resp.read().decode("utf-8")
            self.assertEqual(data, "Hello ServerPy Test")

    def test_path_traversal_blocked_in_read(self):
        url = f"http://{self.host}:{self.port}/api/read?path=../../../../Windows/win.ini"
        req = urllib.request.Request(url, headers=self._auth_headers())
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertIn(ctx.exception.code, (403, 404))

    def test_path_traversal_blocked_in_save(self):
        url = f"http://{self.host}:{self.port}/api/save"
        payload = json.dumps({"path": "../traversal_hack.txt", "content": "Hacked"}).encode()
        req = urllib.request.Request(url, data=payload, headers={**self._auth_headers(), "Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 403)
        self.assertFalse(os.path.exists(os.path.join(self.test_dir, "../traversal_hack.txt")))

    def test_save_and_read_api(self):
        url_save = f"http://{self.host}:{self.port}/api/save"
        payload = json.dumps({"path": "new_created.txt", "content": "Created via API"}).encode()
        req_save = urllib.request.Request(url_save, data=payload, headers={**self._auth_headers(), "Content-Type": "application/json"})
        with urllib.request.urlopen(req_save) as resp:
            self.assertEqual(resp.status, 200)

        url_read = f"http://{self.host}:{self.port}/api/read?path=new_created.txt"
        req_read = urllib.request.Request(url_read, headers=self._auth_headers())
        with urllib.request.urlopen(req_read) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.read().decode("utf-8"), "Created via API")

    def test_mkdir_and_copy_and_delete(self):
        # 1. mkdir
        url_mkdir = f"http://{self.host}:{self.port}/api/mkdir"
        payload = json.dumps({"path": "test_folder"}).encode()
        req_mkdir = urllib.request.Request(url_mkdir, data=payload, headers={**self._auth_headers(), "Content-Type": "application/json"})
        with urllib.request.urlopen(req_mkdir) as resp:
            self.assertEqual(resp.status, 201)

        # 2. copy file into folder
        url_copy = f"http://{self.host}:{self.port}/api/copy"
        payload = json.dumps({"src": "sample.txt", "dst": "test_folder/sample_copy.txt"}).encode()
        req_copy = urllib.request.Request(url_copy, data=payload, headers={**self._auth_headers(), "Content-Type": "application/json"})
        with urllib.request.urlopen(req_copy) as resp:
            self.assertEqual(resp.status, 200)

        self.assertTrue(os.path.isfile(os.path.join(self.test_dir, "test_folder", "sample_copy.txt")))

        # 3. delete via DELETE method
        url_del = f"http://{self.host}:{self.port}/test_folder/sample_copy.txt"
        req_del = urllib.request.Request(url_del, headers=self._auth_headers(), method="DELETE")
        with urllib.request.urlopen(req_del) as resp:
            self.assertEqual(resp.status, 204)

        self.assertFalse(os.path.exists(os.path.join(self.test_dir, "test_folder", "sample_copy.txt")))

    def test_zip_api(self):
        url = f"http://{self.host}:{self.port}/api/zip?path=subfolder"
        req = urllib.request.Request(url, headers=self._auth_headers())
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Content-Type"), "application/zip")
            data = resp.read()
            self.assertTrue(len(data) > 0)
            # Verify zip magic header bytes PK
            self.assertTrue(data.startswith(b"PK"))

    def test_folder_tree_authentication(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"http://{self.host}:{self.port}/api/folders?path=/")
        self.assertEqual(ctx.exception.code, 401)
        ctx.exception.close()

    def test_listing_contains_sortable_metadata(self):
        req = urllib.request.Request(f'http://{self.host}:{self.port}/', headers=self._auth_headers())
        with urllib.request.urlopen(req) as response:
            page = response.read().decode('utf-8')
        self.assertIn('data-size="19"', page)
        self.assertIn('data-modified="', page)
        self.assertIn('data-directory="true"', page)
        self.assertIn('data-allow-mod="true"', page)

    def test_recovery_apis_require_authentication(self):
        for route in ('/api/search?q=sample', '/api/trash', '/api/moves'):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f'http://{self.host}:{self.port}' + route)
            self.assertEqual(caught.exception.code, 401)
            caught.exception.close()
        for route in ('/api/restore', '/api/undo-move'):
            req = urllib.request.Request(f'http://{self.host}:{self.port}' + route, data=b'{"id":"none"}', headers={'Content-Type': 'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req)
            self.assertEqual(caught.exception.code, 401)
            caught.exception.close()

    def test_recovery_and_search_http_flow(self):
        filename = 'recover # 100%20.txt'
        path = os.path.join(self.sub_dir, filename)
        with open(path, 'w', encoding='utf-8') as file:
            file.write('recover through API')
        url = f'http://{self.host}:{self.port}/subfolder/' + urllib.parse.quote(filename, safe='')
        req = urllib.request.Request(url, method='DELETE', headers=self._auth_headers())
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 204)
        self.assertFalse(os.path.exists(path))
        req = urllib.request.Request(f'http://{self.host}:{self.port}/api/trash', headers=self._auth_headers())
        with urllib.request.urlopen(req) as response:
            item = next(item for item in json.load(response)['items'] if item['name'] == filename)
        req = urllib.request.Request(f'http://{self.host}:{self.port}/api/restore', data=json.dumps({'id': item['id']}).encode(), headers={**self._auth_headers(), 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
        query = urllib.parse.urlencode({'q': filename})
        req = urllib.request.Request(f'http://{self.host}:{self.port}/api/search?' + query, headers=self._auth_headers())
        with urllib.request.urlopen(req) as response:
            self.assertEqual(json.load(response)['items'][0]['path'], '/subfolder/' + filename)
        os.remove(path)

    def test_internal_recovery_data_is_not_downloadable(self):
        for route in ('/.serverpy/', '/.serverpy/manifest.json', '/api/read?path=/.serverpy/manifest.json', '/api/zip?path=/.serverpy/'):
            req = urllib.request.Request(f'http://{self.host}:{self.port}' + route, headers=self._auth_headers())
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req)
            self.assertIn(caught.exception.code, (403, 404))
            caught.exception.close()

    def test_restore_readonly_and_search_listing_permissions(self):
        config = self.server_manager.httpd.app_config
        original = config.copy()
        try:
            config['allow_mod'] = False
            req = urllib.request.Request(f'http://{self.host}:{self.port}/api/restore', data=b'{"id":"none"}', headers={**self._auth_headers(), 'Content-Type': 'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req)
            self.assertEqual(caught.exception.code, 405)
            caught.exception.close()
            config['render_pages'] = False
            for route in ('/api/search?q=sample', '/api/trash', '/api/moves'):
                req = urllib.request.Request(f'http://{self.host}:{self.port}' + route, headers=self._auth_headers())
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(req)
                self.assertEqual(caught.exception.code, 403)
                caught.exception.close()
        finally:
            config.update(original)

    def test_upload_conflict_preserves_existing_file(self):
        req = urllib.request.Request(f'http://{self.host}:{self.port}/sample.txt', data=b'overwrite', method='PUT', headers={**self._auth_headers(), 'If-None-Match': '*'})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 412)
        ctx.exception.close()
        with open(self.sample_file, encoding='utf-8') as file:
            self.assertEqual(file.read(), 'Hello ServerPy Test')

    def test_move_conflict_and_descendant_are_rejected(self):
        for payload in ({'src': 'sample.txt', 'dst': 'subfolder/subfile.txt'}, {'src': 'subfolder', 'dst': 'subfolder/inside'}):
            req = urllib.request.Request(f'http://{self.host}:{self.port}/api/move', data=json.dumps(payload).encode(), headers={**self._auth_headers(), 'Content-Type': 'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 409)
            ctx.exception.close()
        self.assertTrue(os.path.isfile(self.sample_file))
        self.assertFalse(os.path.exists(os.path.join(self.sub_dir, 'inside')))

    def test_folder_tree_nested_and_special_names(self):
        with tempfile.TemporaryDirectory(dir=self.test_dir, prefix="tree_") as folder:
            name = "ação # & 100%20"
            os.mkdir(os.path.join(folder, name))
            with open(os.path.join(folder, "hidden_from_tree.txt"), "w") as file:
                file.write("file")
            path = '/' + os.path.basename(folder) + '/'
            url = f"http://{self.host}:{self.port}/api/folders?path=" + urllib.parse.quote(path, safe='')
            req = urllib.request.Request(url, headers=self._auth_headers())
            with urllib.request.urlopen(req) as response:
                self.assertEqual(response.headers.get_content_type(), 'application/json')
                self.assertEqual(json.load(response), {'folders': [{'name': name, 'path': path + name + '/'}]})
            req = urllib.request.Request(url + urllib.parse.quote(name + '/', safe=''), headers=self._auth_headers())
            with urllib.request.urlopen(req) as response:
                self.assertEqual(json.load(response), {'folders': []})

    def test_folder_tree_blocks_traversal(self):
        url = f"http://{self.host}:{self.port}/api/folders?path=" + urllib.parse.quote('/../../', safe='')
        req = urllib.request.Request(url, headers=self._auth_headers())
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 403)
        ctx.exception.close()

    def test_folder_tree_respects_listing_and_readonly_settings(self):
        config = self.server_manager.httpd.app_config
        original = config.copy()
        req = urllib.request.Request(f"http://{self.host}:{self.port}/api/folders?path=/", headers=self._auth_headers())
        try:
            config['allow_mod'] = False
            with urllib.request.urlopen(req) as response:
                self.assertTrue(any(folder['name'] == 'subfolder' for folder in json.load(response)['folders']))
            config['render_pages'] = False
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 403)
            ctx.exception.close()
        finally:
            config.update(original)

class TestServerLifecycle(unittest.TestCase):
    def test_failed_tls_start_keeps_port_available(self):
        manager = ServerManager()
        started, _ = manager.start_server('127.0.0.1', 0, os.getcwd(), use_tls=True, cert_file='missing-cert.pem')
        self.assertFalse(started)
        self.assertIsNone(manager.httpd)
        self.assertIsNone(manager.thread)
        manager.stop_server()
        started, _ = manager.start_server('127.0.0.1', 0, os.getcwd())
        try:
            self.assertTrue(started)
            self.assertGreater(manager.httpd.app_config['port'], 0)
        finally:
            manager.stop_server()


if __name__ == '__main__':
    unittest.main()
