import sys
import ctypes
from ctypes import wintypes

# Win32 Constants
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
SE_PRIVILEGE_ENABLED = 0x00000002

class LUID(ctypes.Structure):
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", wintypes.LONG),
    ]

class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Luid", LUID),
        ("Attributes", wintypes.DWORD),
    ]

class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [
        ("PrivilegeCount", wintypes.DWORD),
        ("Privileges", LUID_AND_ATTRIBUTES * 1),
    ]

def is_admin() -> bool:
    """Verifica se o processo atual possui privilégios de administrador."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def enable_privilege(privilege_name: str) -> bool:
    """Habilita um privilégio NT específico no token de segurança do processo."""
    advapi32 = ctypes.windll.advapi32
    kernel32 = ctypes.windll.kernel32

    h_token = wintypes.HANDLE()
    current_proc = kernel32.GetCurrentProcess()

    if not advapi32.OpenProcessToken(current_proc, TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(h_token)):
        return False

    try:
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, privilege_name, ctypes.byref(luid)):
            return False

        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED

        # Reset last error before adjusting
        kernel32.SetLastError(0)
        ret = advapi32.AdjustTokenPrivileges(
            h_token,
            False,
            ctypes.byref(tp),
            ctypes.sizeof(tp),
            None,
            None
        )
        if not ret or kernel32.GetLastError() != 0:
            return False
        return True
    finally:
        kernel32.CloseHandle(h_token)

def enable_required_privileges() -> tuple[bool, list[str]]:
    """Habilita os privilégios necessários para manipulação da memória física."""
    required = [
        "SeProfileSingleProcessPrivilege",
        "SeIncreaseQuotaPrivilege",
    ]
    all_ok = True
    for priv in required:
        if not enable_privilege(priv):
            all_ok = False
    return all_ok, required

def restart_as_admin(extra_args: list[str] | None = None) -> None:
    """Relança a aplicação solicitando elevação UAC (Administrador)."""
    shell32 = ctypes.windll.shell32
    args = list(sys.argv)
    for arg in extra_args or []:
        if arg not in args:
            args.append(arg)
    params = " ".join([f'"{arg}"' for arg in args])
    shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    sys.exit(0)
