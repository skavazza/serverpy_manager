import ctypes
from ctypes import wintypes
from enum import IntEnum

# NTSTATUS
STATUS_SUCCESS = 0x00000000
STATUS_PRIVILEGE_NOT_HELD = 0xC0000061
STATUS_ACCESS_DENIED = 0xC0000022

class SYSTEM_MEMORY_LIST_COMMAND(IntEnum):
    MemoryEmptyWorkingSets = 0
    MemoryFlushModifiedList = 1
    MemoryPurgeStandbyList = 2
    MemoryPurgeLowPriorityStandbyList = 3
    MemoryEmptyCombineList = 4

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]

    def __init__(self):
        super().__init__()
        self.dwLength = ctypes.sizeof(self)

class PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("CommitTotal", ctypes.c_size_t),
        ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t),
        ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t),
        ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t),
        ("PageSize", ctypes.c_size_t),
        ("HandleCount", wintypes.DWORD),
        ("ProcessCount", wintypes.DWORD),
        ("ThreadCount", wintypes.DWORD),
    ]

    def __init__(self):
        super().__init__()
        self.cb = ctypes.sizeof(self)

class SYSTEM_MEMORY_LIST_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("ZeroPageCount", ctypes.c_size_t),
        ("FreePageCount", ctypes.c_size_t),
        ("ModifiedPageCount", ctypes.c_size_t),
        ("ModifiedNoWritePageCount", ctypes.c_size_t),
        ("BadPageCount", ctypes.c_size_t),
        ("PageCountByPriority", ctypes.c_size_t * 8),
        ("RepurposedPagesByPriority", ctypes.c_size_t * 8),
        ("ModifiedPageCountPageFile", ctypes.c_size_t),
    ]

class SYSTEM_FILECACHE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("CurrentSize", ctypes.c_size_t),
        ("PeakSize", ctypes.c_size_t),
        ("PageFaultCount", wintypes.ULONG),
        ("MinimumWorkingSet", ctypes.c_size_t),
        ("MaximumWorkingSet", ctypes.c_size_t),
        ("CurrentSizeIncludingTransitionInPages", ctypes.c_size_t),
        ("PeakSizeIncludingTransitionInPages", ctypes.c_size_t),
        ("TransitionRePurposeCount", wintypes.ULONG),
        ("Flags", wintypes.ULONG),
    ]

# DLL instances
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi
ntdll = ctypes.windll.ntdll

# Explicit Win32 function signatures for 64-bit safety
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t]
kernel32.SetProcessWorkingSetSize.restype = wintypes.BOOL

psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
psapi.EmptyWorkingSet.restype = wintypes.BOOL

def query_global_memory_status() -> MEMORYSTATUSEX:
    """Consulta o status da memória global física e virtual."""
    stat = MEMORYSTATUSEX()
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        raise ctypes.WinError()
    return stat

def query_performance_info() -> PERFORMANCE_INFORMATION:
    """Consulta métricas de desempenho de memória do sistema via psapi."""
    perf = PERFORMANCE_INFORMATION()
    if not psapi.GetPerformanceInfo(ctypes.byref(perf), ctypes.sizeof(perf)):
        raise ctypes.WinError()
    return perf

def query_system_memory_list_info() -> SYSTEM_MEMORY_LIST_INFORMATION:
    """Consulta contagens de páginas físicas do kernel NT (classe 80)."""
    info = SYSTEM_MEMORY_LIST_INFORMATION()
    ret_len = wintypes.ULONG()
    status = ntdll.NtQuerySystemInformation(
        80, # SystemMemoryListInformation
        ctypes.byref(info),
        ctypes.sizeof(info),
        ctypes.byref(ret_len)
    )
    if status != STATUS_SUCCESS:
        raise OSError(f"NtQuerySystemInformation(80) falhou com NTSTATUS: {hex(status & 0xFFFFFFFF)}")
    return info

def set_system_memory_list(command: int) -> int:
    """Envia um comando de manipulação de lista de memória física (classe 80)."""
    cmd = wintypes.ULONG(command)
    status = ntdll.NtSetSystemInformation(
        80, # SystemMemoryListInformation
        ctypes.byref(cmd),
        ctypes.sizeof(cmd)
    )
    return status & 0xFFFFFFFF

def set_system_filecache(flush: bool = True) -> int:
    """Limpa o Working Set do cache de arquivos do sistema (classe 21)."""
    cache_info = SYSTEM_FILECACHE_INFORMATION()
    if flush:
        max_size = (1 << (ctypes.sizeof(ctypes.c_size_t) * 8)) - 1
        cache_info.MinimumWorkingSet = max_size
        cache_info.MaximumWorkingSet = max_size
    status = ntdll.NtSetSystemInformation(
        21, # SystemFileCacheInformation
        ctypes.byref(cache_info),
        ctypes.sizeof(cache_info)
    )
    return status & 0xFFFFFFFF
