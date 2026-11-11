import ctypes
from ctypes import wintypes
import psutil

from vendor.systemram.core.privileges import is_admin, enable_privilege
from vendor.systemram.core.memory_api import (
    kernel32,
    psapi,
    set_system_memory_list,
    set_system_filecache,
    SYSTEM_MEMORY_LIST_COMMAND,
    STATUS_SUCCESS,
    STATUS_PRIVILEGE_NOT_HELD,
    STATUS_ACCESS_DENIED
)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_QUOTA = 0x0100

def _format_ntstatus_error(status: int) -> str:
    if status in (STATUS_PRIVILEGE_NOT_HELD, STATUS_ACCESS_DENIED):
        return "Permissão insuficiente. Execute o PyRAMMap como Administrador."
    return f"Falha na chamada do kernel do Windows (NTSTATUS: {hex(status)})."

def empty_working_sets() -> tuple[bool, str, int]:
    """
    Esvazia o working set (conjunto de trabalho) de todos os processos possíveis,
    movendo as páginas para a Standby List.
    """
    count_flushed = 0
    total_scanned = 0

    for proc in psutil.process_iter(['pid']):
        try:
            pid = proc.info['pid']
            if pid <= 4:  # Ignora PID 0 (Idle) e PID 4 (System)
                continue

            total_scanned += 1
            h_proc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
            if h_proc:
                try:
                    # Esvazia o conjunto de trabalho do processo
                    if psapi.EmptyWorkingSet(h_proc):
                        count_flushed += 1
                    else:
                        # Alternativa padrão Win32
                        max_size = (1 << (ctypes.sizeof(ctypes.c_size_t) * 8)) - 1
                        if kernel32.SetProcessWorkingSetSize(h_proc, max_size, max_size):
                            count_flushed += 1
                except Exception:
                    pass
                finally:
                    kernel32.CloseHandle(h_proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    msg = f"Conjuntos de trabalho esvaziados em {count_flushed} de {total_scanned} processos."
    return True, msg, count_flushed

def empty_system_working_set() -> tuple[bool, str]:
    """
    Esvazia o cache de arquivos do sistema (System Working Set).
    Requer SeIncreaseQuotaPrivilege.
    """
    enable_privilege("SeIncreaseQuotaPrivilege")
    status = set_system_filecache(flush=True)
    if status == STATUS_SUCCESS:
        return True, "Cache de arquivos do sistema esvaziado com sucesso."
    return False, _format_ntstatus_error(status)

def empty_modified_page_list() -> tuple[bool, str]:
    """
    Grava as páginas modificadas no disco e esvazia a Modified Page List.
    Requer SeProfileSingleProcessPrivilege.
    """
    enable_privilege("SeProfileSingleProcessPrivilege")
    status = set_system_memory_list(SYSTEM_MEMORY_LIST_COMMAND.MemoryFlushModifiedList)
    if status == STATUS_SUCCESS:
        return True, "Lista de páginas modificadas gravada em disco e esvaziada."
    return False, _format_ntstatus_error(status)

def empty_standby_list(priority0_only: bool = False) -> tuple[bool, str]:
    """
    Esvazia a Standby List (todas as prioridades ou apenas Prioridade 0).
    Requer SeProfileSingleProcessPrivilege.
    """
    enable_privilege("SeProfileSingleProcessPrivilege")
    cmd = (
        SYSTEM_MEMORY_LIST_COMMAND.MemoryPurgeLowPriorityStandbyList
        if priority0_only
        else SYSTEM_MEMORY_LIST_COMMAND.MemoryPurgeStandbyList
    )
    status = set_system_memory_list(cmd)
    if status == STATUS_SUCCESS:
        nome = "Standby List (Prioridade 0)" if priority0_only else "Standby List (Completa)"
        return True, f"{nome} esvaziada com sucesso."
    return False, _format_ntstatus_error(status)

def empty_all() -> dict[str, tuple[bool, str]]:
    """Executa todas as operações de limpeza em sequência."""
    ws_ok, ws_msg, _ = empty_working_sets()
    sys_ok, sys_msg = empty_system_working_set()
    mod_ok, mod_msg = empty_modified_page_list()
    stb_ok, stb_msg = empty_standby_list(priority0_only=False)

    return {
        "working_sets": (ws_ok, ws_msg),
        "system_working_set": (sys_ok, sys_msg),
        "modified_page_list": (mod_ok, mod_msg),
        "standby_list": (stb_ok, stb_msg),
    }
