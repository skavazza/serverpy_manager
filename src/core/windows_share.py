"""
Windows network sharing helper for Windows 10 and 11.
Orchestrates parameters, OS compatibility checks, and elevated execution
of the share-folder.ps1 PowerShell script.
"""

import os
import sys
import platform
import subprocess
from pathlib import Path


def is_windows_10_or_11() -> bool:
    """
    Check if the current host operating system is Windows 10 or 11
    (or equivalent Windows Server).
    """
    if sys.platform != "win32":
        return False
    try:
        winver = getattr(sys, "getwindowsversion", lambda: None)()
        if winver is not None:
            # Windows 10 & 11 have major >= 10 (Windows 10 started at build 10240)
            return winver.major >= 10
    except Exception:
        pass
    try:
        rel = platform.release()
        return platform.system() == "Windows" and (rel in ("10", "11") or (rel.isdigit() and int(rel) >= 10))
    except Exception:
        return False


def get_share_script_path() -> str | None:
    """
    Locate the absolute path to share-folder.ps1.
    Checks bundled and legacy layouts in app, project, and working directories.
    """
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
        if hasattr(sys, "_MEIPASS"):
            roots.append(Path(sys._MEIPASS))
    roots.extend((Path(__file__).resolve().parents[2], Path.cwd()))
    candidates = [path for root in roots for path in (
        root / "share-folder" / "share-folder.ps1",
        root / "share-folder.ps1",
    )]
    for p in candidates:
        if p.is_file():
            return str(p.resolve())
    return None


def build_share_args(
    script_path: str,
    folder: str,
    name: str | None = None,
    user: str | None = None,
    access: str = "Escrita",
    without_password: bool = False,
) -> list[str]:
    """
    Build the command-line argument list for powershell.exe executing share-folder.ps1.
    """
    norm_folder = str(Path(folder).resolve())
    # Keep drive root like C:\ intact; strip trailing slash on other paths to avoid CRT escape bugs
    if len(norm_folder) > 3:
        norm_folder = norm_folder.rstrip(r"\/")

    args = [
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", str(Path(script_path).resolve()),
        "-Pasta", norm_folder,
    ]
    if name:
        args.extend(["-Nome", name.strip()])
    if user:
        args.extend(["-Usuario", user.strip()])
    if access in ("Leitura", "Escrita"):
        args.extend(["-Acesso", access])
    if without_password:
        args.append("-SemSenha")
    return args


def _execute_share_linux(
    folder: str,
    name: str | None = None,
    user: str | None = None,
    access: str = "Escrita",
    without_password: bool = False,
) -> tuple[bool, str]:
    if not folder or not os.path.isdir(folder):
        return False, "Select an existing folder."
    
    share_name = name.strip() if name else os.path.basename(os.path.abspath(folder))
    share_name = _sanitize_share_name(share_name)
    if not share_name:
        return False, "Enter a valid share name."

    import shutil
    net_bin = shutil.which("net")
    if not net_bin:
        return False, "Samba (net usershare) is not installed. Install with: sudo apt install samba"

    acl = "Everyone:F" if access == "Escrita" else "Everyone:R"
    guest = "guest_ok=y" if without_password else "guest_ok=n"
    comment = f"Shared by ServerPy on Linux"

    cmd = [net_bin, "usershare", "add", share_name, str(Path(folder).resolve()), comment, acl, guest]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            return True, "Share configured successfully via Samba usershare."
        pkexec_bin = shutil.which("pkexec")
        if pkexec_bin and any(err in res.stderr.lower() for err in ("permissão negada", "permission denied")):
            res_elevated = subprocess.run([pkexec_bin] + cmd, capture_output=True, text=True, timeout=30)
            if res_elevated.returncode == 0:
                return True, "Share configured successfully with administrator privileges."
            return False, res_elevated.stderr.strip() or "Failed to create usershare with elevation."
        return False, res.stderr.strip() or "Unable to create network share."
    except Exception as exc:
        return False, str(exc)


def execute_share_script(
    folder: str,
    name: str | None = None,
    user: str | None = None,
    access: str = "Escrita",
    without_password: bool = False,
    script_path: str | None = None,
) -> tuple[bool, str]:
    """
    Configure folder sharing over the local network on Windows (PowerShell) or Linux (Samba).
    Returns (success: bool, message: str).
    """
    if is_windows_10_or_11() or sys.platform == "win32":
        if not is_windows_10_or_11():
            return False, "Operating system is not Windows 10 or 11."

        if not script_path:
            script_path = get_share_script_path()
        if not script_path or not os.path.isfile(script_path):
            return False, "The share-folder.ps1 script was not found."

        if not folder or not os.path.isdir(folder):
            return False, "Select an existing folder."

        args = build_share_args(
            script_path=script_path,
            folder=folder,
            name=name,
            user=user,
            access=access,
            without_password=without_password,
        )

        cwd = os.path.dirname(script_path) or str(Path(folder).resolve())

        # Method 1: Use ShellExecuteW with "runas" to trigger UAC elevation directly
        try:
            import ctypes
            param_str = subprocess.list2cmdline(args)
            res = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "powershell.exe",
                param_str,
                cwd,
                1,  # SW_SHOWNORMAL
            )
            if res > 32:
                return True, "Share script launched with administrator privileges."
            err = ctypes.GetLastError()
            if err in (1223, 5):  # ERROR_CANCELLED or ERROR_ACCESS_DENIED
                return False, "Operation canceled by user."
        except Exception:
            pass

        # Method 2: Fallback to subprocess.Popen; share-folder.ps1 handles self-elevation
        try:
            creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            cmd = ["powershell.exe"] + args
            subprocess.Popen(cmd, cwd=cwd, creationflags=creation_flags)
            return True, "Share script process started."
        except Exception as exc:
            return False, str(exc)

    if sys.platform.startswith("linux"):
        return _execute_share_linux(folder, name, user, access, without_password)

    return False, "Network sharing is not supported on this platform."


# ---------------------------------------------------------------------------
# SMB share management helpers
# ---------------------------------------------------------------------------

# System/hidden shares that should not be listed or removed by the user.
_SYSTEM_SHARE_SUFFIXES = ("$",)


def _is_system_share(name: str) -> bool:
    """Return True for hidden admin shares like C$, ADMIN$, IPC$."""
    return name.endswith(_SYSTEM_SHARE_SUFFIXES)


def list_smb_shares() -> tuple[bool, list[dict] | str]:
    """
    Query active SMB shares from Windows (PowerShell) or Linux (Samba usershares).
    """
    if is_windows_10_or_11():
        return _list_smb_shares_windows()
    if sys.platform == "win32":
        return False, "Operating system is not Windows 10 or 11."
    if sys.platform.startswith("linux"):
        return _list_smb_shares_linux()
    return False, "Operating system is not supported."


def _list_smb_shares_windows() -> tuple[bool, list[dict] | str]:
    ps_cmd = (
        "$ErrorActionPreference = 'Stop'; "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Get-SmbShare | "
        "Select-Object Name,Path,Description | "
        "ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=15,
        )
        if result.returncode != 0:
            return False, result.stderr.strip() or "Unable to query active shares."
        raw = result.stdout.strip()
        if not raw:
            return True, []

        import json
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]

        shares = []
        for item in data:
            name = (item.get("Name") or "").strip()
            if not name or _is_system_share(name):
                continue
            shares.append(
                {
                    "name": name,
                    "path": (item.get("Path") or "").strip(),
                    "description": (item.get("Description") or "").strip(),
                }
            )
        return True, shares
    except subprocess.TimeoutExpired:
        return False, "Timeout querying active shares."
    except Exception as exc:
        return False, str(exc)


def _list_smb_shares_linux() -> tuple[bool, list[dict] | str]:
    import shutil
    net_bin = shutil.which("net")
    if not net_bin:
        return True, []
    try:
        cmd = [net_bin, "usershare", "info", "--long"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if res.returncode != 0:
            # Shares created with elevation live in a directory the user may not read.
            pkexec_bin = shutil.which("pkexec")
            if pkexec_bin and any(
                err in res.stderr.lower() for err in ("permissão negada", "permission denied")
            ):
                res = subprocess.run([pkexec_bin] + cmd, capture_output=True, text=True, timeout=60)
            if res.returncode != 0:
                return True, []
        shares = []
        current = {}
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                if current and current.get("name"):
                    shares.append(current)
                current = {"name": line[1:-1], "path": "", "description": ""}
            elif "=" in line and current:
                k, v = line.split("=", 1)
                k = k.strip().lower()
                v = v.strip()
                if k == "path":
                    current["path"] = v
                elif k == "comment":
                    current["description"] = v
        if current and current.get("name"):
            shares.append(current)
        return True, shares
    except Exception as exc:
        return False, str(exc)


def _run_elevated_ps(ps_cmd: str, label: str = "Operation") -> tuple[bool, str]:
    """
    Run a PowerShell command with administrator privileges via UAC (ShellExecuteW runas).
    Falls back to a visible console subprocess if ShellExecuteW is unavailable.

    Returns (success: bool, message: str).
    """
    # Method 1: ShellExecuteW runas → UAC prompt (silent window)
    try:
        import ctypes
        param_str = subprocess.list2cmdline(
            ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd]
        )
        res = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", param_str, None, 1)
        if res > 32:
            return True, f"{label} launched with administrator privileges."
        err = ctypes.GetLastError()
        if err in (1223, 5):  # ERROR_CANCELLED or ERROR_ACCESS_DENIED
            return False, "Operation canceled by user."
    except Exception:
        pass

    # Method 2: Subprocess fallback (opens a console window)
    try:
        creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            creationflags=creation_flags,
        )
        return True, f"{label} process started."
    except Exception as exc:
        return False, str(exc)


def _remove_smb_share_linux(name: str) -> tuple[bool, str]:
    import shutil
    net_bin = shutil.which("net")
    if not net_bin:
        return False, "Samba (net usershare) is not installed."
    cmd = [net_bin, "usershare", "delete", name]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            return True, f"Share '{name}' removed successfully."
        pkexec_bin = shutil.which("pkexec")
        if pkexec_bin and any(err in res.stderr.lower() for err in ("permissão negada", "permission denied")):
            res_elevated = subprocess.run([pkexec_bin] + cmd, capture_output=True, text=True, timeout=30)
            if res_elevated.returncode == 0:
                return True, f"Share '{name}' removed with administrator privileges."
        return False, res.stderr.strip() or f"Unable to remove share '{name}'."
    except Exception as exc:
        return False, str(exc)


def remove_smb_share(name: str) -> tuple[bool, str]:
    """
    Remove an SMB share by name on Windows or Linux.
    """
    if is_windows_10_or_11():
        if not name or _is_system_share(name):
            return False, "Invalid or protected share name."
        safe_name = name.replace("'", "''")
        ps_cmd = f"Remove-SmbShare -Name '{safe_name}' -Force"
        return _run_elevated_ps(ps_cmd, f"Share '{name}' removal")
    if sys.platform == "win32":
        return False, "Operating system is not Windows 10 or 11."
    if sys.platform.startswith("linux"):
        return _remove_smb_share_linux(name)
    return False, "Operating system is not supported."


# ---------------------------------------------------------------------------
# Printer sharing helpers
# ---------------------------------------------------------------------------

def _list_printers_windows() -> tuple[bool, list[dict] | str]:
    ps_cmd = (
        "$ErrorActionPreference = 'Stop'; "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Get-Printer | "
        "Select-Object Name,ShareName,Shared,DriverName,PortName | "
        "ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=15,
        )
        if result.returncode != 0:
            return False, result.stderr.strip() or "Unable to query printers."
        raw = result.stdout.strip()
        if not raw:
            return True, []

        import json
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]

        printers = []
        for item in data:
            name = (item.get("Name") or "").strip()
            if not name:
                continue
            printers.append(
                {
                    "name": name,
                    "share_name": (item.get("ShareName") or "").strip(),
                    "shared": bool(item.get("Shared", False)),
                    "driver": (item.get("DriverName") or "").strip(),
                    "port": (item.get("PortName") or "").strip(),
                }
            )
        return True, printers
    except subprocess.TimeoutExpired:
        return False, "Timeout querying printers."
    except Exception as exc:
        return False, str(exc)


def _list_printers_linux() -> tuple[bool, list[dict] | str]:
    import shutil
    import re
    lpstat_bin = shutil.which("lpstat")
    if not lpstat_bin:
        return True, []
    try:
        res = subprocess.run([lpstat_bin, "-p"], capture_output=True, text=True, timeout=10)
        printers = []
        for line in res.stdout.splitlines():
            m = re.match(r"^printer\s+([^\s]+)", line.strip())
            if m:
                pname = m.group(1)
                printers.append({
                    "name": pname,
                    "share_name": pname,
                    "shared": True,
                    "driver": "CUPS",
                    "port": "IPP",
                })
        if not printers:
            res_e = subprocess.run([lpstat_bin, "-e"], capture_output=True, text=True, timeout=10)
            if res_e.returncode == 0:
                for line in res_e.stdout.splitlines():
                    pname = line.strip()
                    if pname:
                        printers.append({
                            "name": pname,
                            "share_name": pname,
                            "shared": True,
                            "driver": "CUPS",
                            "port": "IPP",
                        })
        return True, printers
    except Exception as exc:
        return False, str(exc)


def list_printers() -> tuple[bool, list[dict] | str]:
    """
    Query installed printers and their network-sharing status without elevation.
    """
    if is_windows_10_or_11():
        return _list_printers_windows()
    if sys.platform == "win32":
        return False, "Operating system is not Windows 10 or 11."
    if sys.platform.startswith("linux"):
        return _list_printers_linux()
    return False, "Operating system is not supported."


def _sanitize_share_name(name: str) -> str:
    """Strip characters invalid in a Windows share name."""
    import re
    return re.sub(r'[\\/:*?"<>|]', "", name).strip()[:80]


def _share_printer_linux(printer_name: str, share_name: str) -> tuple[bool, str]:
    import shutil
    lpadmin_bin = shutil.which("lpadmin")
    if not lpadmin_bin:
        return False, "CUPS (lpadmin) is not installed."
    cmd = [lpadmin_bin, "-p", printer_name, "-o", "printer-is-shared=true"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return True, f"Printer '{printer_name}' shared via CUPS."
        pkexec_bin = shutil.which("pkexec")
        if pkexec_bin:
            res_el = subprocess.run([pkexec_bin] + cmd, capture_output=True, text=True, timeout=20)
            if res_el.returncode == 0:
                return True, f"Printer '{printer_name}' shared via CUPS."
        return False, res.stderr.strip() or "Failed to share printer."
    except Exception as exc:
        return False, str(exc)


def _unshare_printer_linux(printer_name: str) -> tuple[bool, str]:
    import shutil
    lpadmin_bin = shutil.which("lpadmin")
    if not lpadmin_bin:
        return False, "CUPS (lpadmin) is not installed."
    cmd = [lpadmin_bin, "-p", printer_name, "-o", "printer-is-shared=false"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return True, f"Printer '{printer_name}' unshared via CUPS."
        pkexec_bin = shutil.which("pkexec")
        if pkexec_bin:
            res_el = subprocess.run([pkexec_bin] + cmd, capture_output=True, text=True, timeout=20)
            if res_el.returncode == 0:
                return True, f"Printer '{printer_name}' unshared via CUPS."
        return False, res.stderr.strip() or "Failed to unshare printer."
    except Exception as exc:
        return False, str(exc)


def share_printer(printer_name: str, share_name: str) -> tuple[bool, str]:
    """
    Share a printer over the network.
    """
    if is_windows_10_or_11():
        if not printer_name:
            return False, "Select a printer to share."
        if not share_name:
            return False, "Enter a valid share name for the printer."

        safe_printer = printer_name.replace("'", "''")
        safe_share = _sanitize_share_name(share_name).replace("'", "''")
        if not safe_share:
            return False, "Enter a valid share name for the printer."

        ps_cmd = (
            "Start-Service -Name Spooler -ErrorAction SilentlyContinue; "
            f"Set-Printer -Name '{safe_printer}' -Shared $True -ShareName '{safe_share}'"
        )
        return _run_elevated_ps(ps_cmd, f"Printer '{printer_name}' sharing")
    if sys.platform == "win32":
        return False, "Operating system is not Windows 10 or 11."
    if sys.platform.startswith("linux"):
        return _share_printer_linux(printer_name, share_name)
    return False, "Operating system is not supported."


def unshare_printer(printer_name: str) -> tuple[bool, str]:
    """
    Stop sharing a printer.
    """
    if is_windows_10_or_11():
        if not printer_name:
            return False, "Select a printer to stop sharing."

        safe_printer = printer_name.replace("'", "''")
        ps_cmd = f"Set-Printer -Name '{safe_printer}' -Shared $False -ShareName ''"
        return _run_elevated_ps(ps_cmd, f"Printer '{printer_name}' unsharing")
    if sys.platform == "win32":
        return False, "Operating system is not Windows 10 or 11."
    if sys.platform.startswith("linux"):
        return _unshare_printer_linux(printer_name)
    return False, "Operating system is not supported."

