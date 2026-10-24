import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialogButtonBox
from src.core.windows_share import (
    is_windows_10_or_11,
    get_share_script_path,
    build_share_args,
    execute_share_script,
)
from src.gui.dialogs import ShareFolderDialog, PrinterSharingDialog
from src.gui.i18n import InterfaceLanguage
from src.gui.controller import AppController


class TestWindowsShareCore(unittest.TestCase):
    def test_failed_queries_are_reported_instead_of_empty_results(self):
        from src.core.windows_share import list_printers, list_smb_shares
        with patch("src.core.windows_share.is_windows_10_or_11", return_value=True), patch(
            "src.core.windows_share.subprocess.run",
            return_value=SimpleNamespace(returncode=1, stdout="", stderr="Access denied"),
        ):
            for query in (list_printers, list_smb_shares):
                self.assertEqual(query(), (False, "Access denied"))

    def test_printer_query_preserves_names_and_sharing_status(self):
        from src.core.windows_share import list_printers
        result = SimpleNamespace(
            returncode=0,
            stdout='{"Name":"Recepção","ShareName":"","Shared":false,"DriverName":"Driver","PortName":"USB001"}',
            stderr="",
        )
        with patch("src.core.windows_share.is_windows_10_or_11", return_value=True), patch(
            "src.core.windows_share.subprocess.run", return_value=result
        ):
            ok, printers = list_printers()
        self.assertTrue(ok)
        self.assertEqual(printers[0]["name"], "Recepção")
        self.assertFalse(printers[0]["shared"])

    def test_is_windows_10_or_11_detection(self):
        # On non-Windows platforms
        with patch("sys.platform", "linux"):
            self.assertFalse(is_windows_10_or_11())

        # Windows 10 / 11 (major 10)
        win10 = SimpleNamespace(major=10, minor=0, build=19045, platform=2, service_pack="")
        with patch("sys.platform", "win32"), patch("sys.getwindowsversion", return_value=win10, create=True):
            self.assertTrue(is_windows_10_or_11())

        # Windows 7 (major 6, minor 1)
        win7 = SimpleNamespace(major=6, minor=1, build=7601, platform=2, service_pack="")
        with patch("sys.platform", "win32"), patch("sys.getwindowsversion", return_value=win7, create=True):
            with patch("platform.system", return_value="Windows"), patch("platform.release", return_value="7"):
                self.assertFalse(is_windows_10_or_11())

        # Platform release fallback
        with patch("sys.platform", "win32"), patch("sys.getwindowsversion", create=True, side_effect=AttributeError):
            with patch("platform.system", return_value="Windows"), patch("platform.release", return_value="11"):
                self.assertTrue(is_windows_10_or_11())

    def test_get_share_script_path(self):
        path = get_share_script_path()
        self.assertIsNotNone(path)
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(path.lower().endswith("share-folder.ps1"))

    def test_script_discovery_supports_project_and_frozen_layouts(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            project = root / 'project'
            bundle = root / 'bundle'
            working = root / 'working'
            working.mkdir()
            for origin in (project, bundle):
                for nested in (True, False):
                    with self.subTest(origin=origin.name, nested=nested):
                        script = origin / 'share-folder' / 'share-folder.ps1' if nested else origin / 'share-folder.ps1'
                        script.parent.mkdir(parents=True, exist_ok=True)
                        script.write_text('# discovery fixture', encoding='utf-8')
                        try:
                            with patch('src.core.windows_share.__file__', str(project / 'src' / 'core' / 'windows_share.py')), patch(
                                'src.core.windows_share.Path.cwd', return_value=working
                            ), patch.object(sys, 'frozen', origin == bundle, create=True), patch.object(
                                sys, '_MEIPASS', str(bundle), create=True
                            ), patch.object(sys, 'executable', str(root / 'app' / 'serverpy.exe')):
                                self.assertEqual(get_share_script_path(), str(script.resolve()))
                        finally:
                            script.unlink()

    def test_build_share_args(self):
        script = r"C:\ServerPy\share-folder.ps1"
        folder = r"C:\My Projects\Files"
        args = build_share_args(
            script_path=script,
            folder=folder,
            name="Files",
            user="Todos",
            access="Escrita",
            without_password=True,
        )

        self.assertIn("-NoProfile", args)
        self.assertIn("-ExecutionPolicy", args)
        self.assertIn("Bypass", args)
        self.assertIn("-Pasta", args)
        self.assertIn(str(Path(folder).resolve()), args)
        self.assertIn("-Nome", args)
        self.assertIn("Files", args)
        self.assertIn("-Usuario", args)
        self.assertIn("Todos", args)
        self.assertIn("-Acesso", args)
        self.assertIn("Escrita", args)
        self.assertIn("-SemSenha", args)

    def test_execute_share_script_validations(self):
        # Rejects if not Windows 10/11
        with patch("sys.platform", "win32"), patch("src.core.windows_share.is_windows_10_or_11", return_value=False):
            ok, msg = execute_share_script("C:\\test")
            self.assertFalse(ok)
            self.assertIn("Operating system is not Windows 10 or 11", msg)

        # Rejects if script not found
        with patch("src.core.windows_share.is_windows_10_or_11", return_value=True):
            with patch("src.core.windows_share.get_share_script_path", return_value=None):
                ok, msg = execute_share_script("C:\\test")
                self.assertFalse(ok)
                self.assertIn("not found", msg)

        # Rejects if folder does not exist
        with patch("src.core.windows_share.is_windows_10_or_11", return_value=True):
            with tempfile.NamedTemporaryFile() as temp_script:
                ok, msg = execute_share_script("C:\\nonexistent_folder_xyz_123", script_path=temp_script.name)
                self.assertFalse(ok)
                self.assertIn("existing folder", msg)

    def test_execute_share_script_linux_uses_samba_usershare(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("sys.platform", "linux"), patch("src.core.windows_share.is_windows_10_or_11", return_value=False):
                with patch("shutil.which", side_effect=lambda tool: "/usr/bin/net" if tool == "net" else None):
                    with patch("src.core.windows_share.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as run:
                        ok, msg = execute_share_script(temp_dir, name="ServerPyLinuxShare", without_password=True)
                        self.assertTrue(ok)
                        self.assertIn("Share configured successfully", msg)
                        run.assert_called_once()

    def test_execute_share_script_shellexecute_success(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.NamedTemporaryFile() as temp_script:
            with patch("src.core.windows_share.is_windows_10_or_11", return_value=True):
                mock_shell32 = MagicMock()
                mock_shell32.ShellExecuteW.return_value = 42  # Success > 32
                with patch.dict("sys.modules", {"ctypes": MagicMock(windll=MagicMock(shell32=mock_shell32))}):
                    ok, msg = execute_share_script(temp_dir, name="TempShare", script_path=temp_script.name)
                    self.assertTrue(ok)
                    self.assertIn("administrator privileges", msg)
                    mock_shell32.ShellExecuteW.assert_called_once()
                    call_args = mock_shell32.ShellExecuteW.call_args[0]
                    self.assertEqual(call_args[1], "runas")
                    self.assertEqual(call_args[2], "powershell.exe")
                    self.assertIn("-Pasta", call_args[3])
                    self.assertIn("TempShare", call_args[3])

    def test_execute_share_script_user_cancelled(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.NamedTemporaryFile() as temp_script:
            with patch("src.core.windows_share.is_windows_10_or_11", return_value=True):
                mock_ctypes = MagicMock()
                mock_ctypes.windll.shell32.ShellExecuteW.return_value = 0  # Failed / cancelled <= 32
                mock_ctypes.GetLastError.return_value = 1223  # ERROR_CANCELLED
                with patch.dict("sys.modules", {"ctypes": mock_ctypes}):
                    ok, msg = execute_share_script(temp_dir, script_path=temp_script.name)
                    self.assertFalse(ok)
                    self.assertIn("canceled by user", msg)


class TestShareFolderDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_dialog_initialization_and_prefill(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dialog = ShareFolderDialog(initial_folder=temp_dir, language=InterfaceLanguage("en"))
            self.assertEqual(dialog.windowTitle(), "Share folder on network")
            self.assertEqual(dialog.line_folder.text(), temp_dir)
            self.assertEqual(dialog.line_name.text(), Path(temp_dir).name)
            self.assertEqual(dialog.line_user.text(), "Todos")
            self.assertEqual(dialog.combo_access.currentData(), "Escrita")
            self.assertFalse(dialog.chk_no_password.isChecked())

    def test_dialog_validation_and_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dialog = ShareFolderDialog(initial_folder=temp_dir, language=InterfaceLanguage("pt"))
            self.assertEqual(dialog.windowTitle(), "Compartilhar pasta na rede")

            # Non-existent folder
            dialog.line_folder.setText("C:\\nonexistent_dir_999")
            dialog.accept()
            self.assertEqual(dialog.result(), 0)
            self.assertFalse(dialog.error.isHidden())
            self.assertIn("pasta existente", dialog.error.text())

            # Invalid share name
            dialog.line_folder.setText(temp_dir)
            dialog.line_name.setText("Invalid/Share:Name*")
            dialog.accept()
            self.assertEqual(dialog.result(), 0)
            self.assertFalse(dialog.error.isHidden())

            # Valid configuration
            dialog.line_name.setText("ValidShare")
            dialog.line_user.setText("Administrador")
            dialog.combo_access.setCurrentIndex(1)  # Leitura
            dialog.chk_no_password.setChecked(True)
            dialog.accept()
            self.assertEqual(dialog.result(), 1)

            cfg = dialog.get_config()
            self.assertEqual(cfg["folder"], os.path.abspath(temp_dir))
            self.assertEqual(cfg["name"], "ValidShare")
            self.assertEqual(cfg["user"], "Administrador")
            self.assertEqual(cfg["access"], "Leitura")
            self.assertTrue(cfg["without_password"])

    def test_dialog_translation_toggle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lang = InterfaceLanguage("pt")
            dialog = ShareFolderDialog(initial_folder=temp_dir, language=lang)
            self.assertEqual(dialog.buttons.button(QDialogButtonBox.Ok).text(), "Compartilhar na rede")
            self.assertEqual(dialog.buttons.button(QDialogButtonBox.Cancel).text(), "Cancelar")
            self.assertEqual(dialog.combo_access.itemText(0), "Leitura e escrita")
            self.assertEqual(dialog.combo_access.itemText(1), "Somente leitura")

            lang.code = "en"
            dialog.retranslate()
            self.assertEqual(dialog.buttons.button(QDialogButtonBox.Ok).text(), "Share on Network")
            self.assertEqual(dialog.buttons.button(QDialogButtonBox.Cancel).text(), "Cancel")
            self.assertEqual(dialog.combo_access.itemText(0), "Read and write")
            self.assertEqual(dialog.combo_access.itemText(1), "Read only")


class TestControllerShareIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_streams = sys.stdout, sys.stderr
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="serverpy_share_")

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()
        sys.stdout, sys.stderr = cls.original_streams

    def test_share_network_button_visibility_and_action(self):
        with patch("src.gui.controller.is_windows_10_or_11", return_value=True):
            controller = AppController()
            btn = controller.window.btn_share_network
            self.assertFalse(btn.isHidden())
            self.assertTrue(btn.isEnabled())

            # Portuguese translation check
            controller.language_combo.setCurrentIndex(1)
            self.assertEqual(btn.text(), "COMPARTILHAR PASTA NA REDE")

            # English translation check
            controller.language_combo.setCurrentIndex(0)
            self.assertEqual(btn.text(), "SHARE FOLDER ON NETWORK")

            # Click action executes script through dialog
            mock_dialog = MagicMock()
            mock_dialog.exec.return_value = 1
            mock_dialog.get_config.return_value = {
                "folder": self.temp_dir.name,
                "name": "TestShare",
                "user": "Todos",
                "access": "Escrita",
                "without_password": False,
            }
            with patch("src.gui.controller.ShareFolderDialog", return_value=mock_dialog):
                with patch("src.gui.controller.execute_share_script", return_value=(True, "OK")) as mock_exec:
                    controller.on_share_folder_network()
                    mock_exec.assert_called_once_with(
                        folder=self.temp_dir.name,
                        name="TestShare",
                        user="Todos",
                        access="Escrita",
                        without_password=False,
                        script_path=get_share_script_path(),
                    )

            controller.schedule_timer.stop()
            controller.window.close()
            controller.log_window.close()

    def test_share_network_hidden_when_not_win10_or_11(self):
        with patch("src.gui.controller.is_windows_10_or_11", return_value=False), patch("src.gui.controller.is_platform_supported", return_value=False):
            controller = AppController()
            btn = controller.window.btn_share_network
            self.assertTrue(btn.isHidden())
            self.assertTrue(controller.window.btn_share_printers.isHidden())
            controller.schedule_timer.stop()
            controller.window.close()
            controller.log_window.close()

    def test_share_network_visible_on_linux(self):
        with patch("src.gui.controller.is_windows_10_or_11", return_value=False), patch("src.gui.controller.is_platform_supported", return_value=True):
            controller = AppController()
            btn = controller.window.btn_share_network
            self.assertFalse(btn.isHidden())
            self.assertTrue(btn.isEnabled())
            controller.schedule_timer.stop()
            controller.window.close()
            controller.log_window.close()

    def test_printer_button_translation_and_dialog(self):
        with patch("src.gui.controller.is_windows_10_or_11", return_value=True):
            controller = AppController()
        try:
            btn = controller.window.btn_share_printers
            self.assertFalse(btn.isHidden())
            controller.language_combo.setCurrentIndex(1)
            self.assertEqual(btn.text(), "COMPARTILHAR IMPRESSORAS NA REDE")
            with patch("src.gui.controller.PrinterSharingDialog") as dialog:
                btn.click()
                dialog.assert_called_once_with(controller.window, controller.language)
                dialog.return_value.exec.assert_called_once()
        finally:
            controller.schedule_timer.stop()
            controller.window.close()
            controller.log_window.close()


class TestPrinterSharingDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_selection_sharing_and_failed_refresh(self):
        printers = [{"name": "Recepção", "share_name": "", "shared": False,
                     "driver": "Driver", "port": "USB001"}]
        with patch("src.core.windows_share.list_printers", return_value=(True, printers)):
            dialog = PrinterSharingDialog(language=InterfaceLanguage("pt"))
        try:
            self.assertEqual(dialog.windowTitle(), "Compartilhamento de impressoras")
            dialog.table.selectRow(0)
            self.assertTrue(dialog.btn_share.isEnabled())
            self.assertFalse(dialog.btn_unshare.isEnabled())
            dialog.line_share_name.setText("Recepcao")
            with patch("src.core.windows_share.share_printer", return_value=(True, "Started")) as share, patch.object(
                dialog, "_schedule_refresh"
            ) as refresh:
                dialog.share_selected()
                share.assert_called_once_with("Recepção", "Recepcao")
                refresh.assert_called_once()
            with patch("src.core.windows_share.list_printers", return_value=(False, "Timeout querying printers.")):
                dialog.refresh_printers()
            self.assertFalse(dialog.btn_share.isEnabled())
            self.assertFalse(dialog.btn_unshare.isEnabled())
            self.assertEqual(dialog.status_label.text(), "Tempo esgotado ao consultar impressoras.")
        finally:
            dialog.close()
