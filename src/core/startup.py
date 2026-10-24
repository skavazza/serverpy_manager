"""Per-user automatic startup registration for Windows (Registry) and Linux (XDG Autostart)."""
import os
from pathlib import Path
import subprocess
import sys


class StartupRegistration:
    KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
    VALUE = 'ServerPyHTTPManager'

    def __init__(self):
        self.supported = sys.platform == 'win32' or sys.platform.startswith('linux')
        self.registry = None
        if sys.platform == 'win32':
            try:
                import winreg
                self.registry = winreg
            except ImportError:
                pass

    def _linux_desktop_path(self):
        return Path(os.path.expanduser('~/.config/autostart')) / 'serverpy.desktop'

    def command(self):
        executable = Path(sys.executable).resolve()
        if getattr(sys, 'frozen', False):
            args = [str(executable)]
        else:
            if self.registry is not None or sys.platform == 'win32':
                windowed = executable.with_name('pythonw.exe')
                if not windowed.is_file():
                    raise OSError('pythonw.exe is missing from the Python environment.')
                main = Path(__file__).resolve().parents[1] / 'main.py'
                args = [str(windowed), str(main)]
            else:
                main = Path(__file__).resolve().parents[1] / 'main.py'
                args = [str(executable), str(main)]
        args.append('--autostart')
        command = subprocess.list2cmdline(args)
        if (self.registry is not None or sys.platform == 'win32') and len(command) > 260:
            raise OSError('The startup command exceeds the Windows limit of 260 characters.')
        return command

    def is_enabled(self):
        if not self.supported:
            return False
        if self.registry is not None or sys.platform == 'win32':
            registry = self.registry
            if not registry:
                return False
            try:
                with registry.OpenKey(registry.HKEY_CURRENT_USER, self.KEY) as key:
                    value, kind = registry.QueryValueEx(key, self.VALUE)
                return kind == registry.REG_SZ and value == self.command()
            except FileNotFoundError:
                return False
        else:
            path = self._linux_desktop_path()
            if not path.is_file():
                return False
            try:
                content = path.read_text(encoding='utf-8')
                cmd = self.command()
                return f"Exec={cmd}" in content
            except OSError:
                return False

    def set_enabled(self, enabled):
        if not self.supported:
            raise OSError('Automatic startup is not supported on this platform.')
        if self.registry is not None or sys.platform == 'win32':
            registry = self.registry
            if not registry:
                raise OSError('Windows registry is not available.')
            if enabled:
                command = self.command()
                with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, self.KEY, 0, registry.KEY_SET_VALUE) as key:
                    registry.SetValueEx(key, self.VALUE, 0, registry.REG_SZ, command)
            else:
                try:
                    with registry.OpenKey(registry.HKEY_CURRENT_USER, self.KEY, 0, registry.KEY_SET_VALUE) as key:
                        registry.DeleteValue(key, self.VALUE)
                except FileNotFoundError:
                    pass
        else:
            path = self._linux_desktop_path()
            if enabled:
                path.parent.mkdir(parents=True, exist_ok=True)
                cmd = self.command()
                entry = (
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Version=1.0\n"
                    "Name=ServerPy HTTP Manager\n"
                    "Comment=ServerPy HTTP Server and File Manager\n"
                    f"Exec={cmd}\n"
                    "Terminal=false\n"
                    "Categories=Network;Utility;\n"
                    "X-GNOME-Autostart-enabled=true\n"
                )
                path.write_text(entry, encoding='utf-8')
            else:
                try:
                    if path.is_file():
                        path.unlink()
                except OSError:
                    pass

