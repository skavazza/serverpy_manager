from dataclasses import dataclass
from typing import Any
import psutil

from vendor.systemram.core.memory_api import (
    query_global_memory_status,
    query_performance_info,
    query_system_memory_list_info,
)

@dataclass
class MemorySummary:
    total_bytes: int
    in_use_bytes: int
    modified_bytes: int
    standby_bytes: int
    free_bytes: int
    zeroed_bytes: int
    system_cache_bytes: int
    paged_pool_bytes: int
    nonpaged_pool_bytes: int
    load_percent: float

    @property
    def total_mb(self) -> float:
        return self.total_bytes / (1024 * 1024)

    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024 * 1024 * 1024)

    @property
    def in_use_mb(self) -> float:
        return self.in_use_bytes / (1024 * 1024)

    @property
    def standby_mb(self) -> float:
        return self.standby_bytes / (1024 * 1024)

    @property
    def free_mb(self) -> float:
        return self.free_bytes / (1024 * 1024)

    @property
    def modified_mb(self) -> float:
        return self.modified_bytes / (1024 * 1024)

@dataclass
class ProcessMemoryInfo:
    pid: int
    name: str
    working_set: int
    private_bytes: int
    commit_bytes: int
    paged_pool: int
    nonpaged_pool: int

    @property
    def working_set_mb(self) -> float:
        return self.working_set / (1024 * 1024)

    @property
    def private_mb(self) -> float:
        return self.private_bytes / (1024 * 1024)

def get_memory_summary() -> MemorySummary:
    """Coleta e sintetiza as métricas globais da memória física e de paginação."""
    stat = query_global_memory_status()
    perf = query_performance_info()
    page_size = perf.PageSize if perf.PageSize > 0 else 4096

    try:
        sys_list = query_system_memory_list_info()
        standby_pages = sum(sys_list.PageCountByPriority)
        modified_pages = sys_list.ModifiedPageCount
        free_pages = sys_list.FreePageCount
        zeroed_pages = sys_list.ZeroPageCount
    except Exception:
        # Fallback caso a chamada ao kernel não esteja disponível
        standby_pages = 0
        modified_pages = 0
        free_pages = perf.PhysicalAvailable
        zeroed_pages = 0

    standby_bytes = standby_pages * page_size
    modified_bytes = modified_pages * page_size
    free_bytes = free_pages * page_size
    zeroed_bytes = zeroed_pages * page_size
    total_bytes = int(stat.ullTotalPhys)

    # Memória em uso (Ativa) = Total - (Standby + Modificada + Livre + Zerada)
    in_use_bytes = max(0, total_bytes - (standby_bytes + modified_bytes + free_bytes + zeroed_bytes))

    return MemorySummary(
        total_bytes=total_bytes,
        in_use_bytes=in_use_bytes,
        modified_bytes=modified_bytes,
        standby_bytes=standby_bytes,
        free_bytes=free_bytes,
        zeroed_bytes=zeroed_bytes,
        system_cache_bytes=perf.SystemCache * page_size,
        paged_pool_bytes=perf.KernelPaged * page_size,
        nonpaged_pool_bytes=perf.KernelNonpaged * page_size,
        load_percent=float(stat.dwMemoryLoad),
    )

def get_priority_breakdown() -> list[dict[str, Any]]:
    """Retorna o consumo de memória para cada um dos 8 níveis de prioridade da lista Standby."""
    perf = query_performance_info()
    page_size = perf.PageSize if perf.PageSize > 0 else 4096
    sys_list = query_system_memory_list_info()

    total_standby_pages = sum(sys_list.PageCountByPriority)
    total_standby_bytes = total_standby_pages * page_size

    breakdown = []
    for priority, count in enumerate(sys_list.PageCountByPriority):
        b = count * page_size
        pct = (b / total_standby_bytes * 100) if total_standby_bytes > 0 else 0.0
        breakdown.append({
            "priority": priority,
            "pages": count,
            "bytes": b,
            "mb": round(b / (1024 * 1024), 2),
            "percent": round(pct, 2),
        })

    return breakdown

def get_processes_memory_list() -> list[ProcessMemoryInfo]:
    """Enumera os processos ativos e seus respectivos usos de memória física e virtual."""
    proc_list = []
    for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
        try:
            info = proc.info
            mem = info.get('memory_info')
            if not mem:
                continue

            # Extração dos campos disponíveis em Windows psutil
            working_set = getattr(mem, 'rss', 0)
            private_bytes = getattr(mem, 'private', getattr(mem, 'vms', 0))
            commit_bytes = getattr(mem, 'vms', 0)
            paged_pool = getattr(mem, 'paged_pool', 0)
            nonpaged_pool = getattr(mem, 'nonpaged_pool', 0)

            proc_list.append(ProcessMemoryInfo(
                pid=info['pid'],
                name=info.get('name') or "Desconhecido",
                working_set=working_set,
                private_bytes=private_bytes,
                commit_bytes=commit_bytes,
                paged_pool=paged_pool,
                nonpaged_pool=nonpaged_pool,
            ))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Ordena decrescente por Working Set (maiores consumidores primeiro)
    proc_list.sort(key=lambda p: p.working_set, reverse=True)
    return proc_list
