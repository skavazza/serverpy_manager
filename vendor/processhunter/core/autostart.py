from __future__ import annotations
import os
import sys
import winreg
from pathlib import Path


class WindowsAutostart:
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def __init__(self, app_name: str = "ProcessHunter") -> None:
        self.app_name = app_name

    def is_enabled(self) -> bool:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self.REG_PATH,
                0,
                winreg.KEY_READ
            ) as key:
                winreg.QueryValueEx(key, self.app_name)
                return True
        except (FileNotFoundError, OSError):
            return False

    def enable(
        self,
        entrypoint_path: str,
        python_exe: str | None = None,
        start_minimized: bool = True
    ) -> bool:
        try:
            if not python_exe:
                # Prefer pythonw.exe to avoid console flashing if available
                current_exe = Path(sys.executable)
                pythonw = current_exe.parent / "pythonw.exe"
                python_exe = str(pythonw if pythonw.exists() else current_exe)

            cmd = f'"{python_exe}" "{entrypoint_path}"'
            if start_minimized:
                cmd += " --minimized"

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self.REG_PATH,
                0,
                winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(
                    key,
                    self.app_name,
                    0,
                    winreg.REG_SZ,
                    cmd
                )
            return True
        except OSError:
            return False

    def disable(self) -> bool:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self.REG_PATH,
                0,
                winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, self.app_name)
            return True
        except FileNotFoundError:
            # Already not present
            return True
        except OSError:
            return False
