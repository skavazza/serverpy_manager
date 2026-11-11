from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List
import psutil


@dataclass
class ProcessInfo:
    pid: int
    name: str
    memory_mb: float
    status: str


@dataclass
class KillResult:
    pid: int
    name: str
    success: bool
    error_message: str = ""


class ProcessHunter:
    @staticmethod
    def normalize_name(name: str) -> str:
        cleaned = name.strip()
        cleaned = re.sub(r'(?i)\.exe$', '', cleaned)
        return cleaned.lower()

    def scan_active_processes(self) -> List[ProcessInfo]:
        results: List[ProcessInfo] = []
        for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'status']):
            try:
                info = proc.info
                pid = info.get('pid', 0)
                name = info.get('name') or "Desconhecido"
                mem_info = info.get('memory_info')
                rss_bytes = getattr(mem_info, 'rss', 0) if mem_info else 0
                memory_mb = round(rss_bytes / (1024 * 1024), 2)
                status = info.get('status') or "unknown"

                results.append(ProcessInfo(
                    pid=pid,
                    name=name,
                    memory_mb=memory_mb,
                    status=str(status)
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        results.sort(key=lambda p: p.name.lower())
        return results

    def kill_targets(self, target_names: List[str]) -> List[KillResult]:
        normalized_targets = {self.normalize_name(t) for t in target_names if t.strip()}
        if not normalized_targets:
            return []

        results: List[KillResult] = []

        for proc in psutil.process_iter(['pid', 'name']):
            try:
                info = proc.info
                raw_name = info.get('name') or ''
                norm_name = self.normalize_name(raw_name)
                pid = info.get('pid', 0)

                if norm_name in normalized_targets:
                    try:
                        proc.kill()
                        results.append(KillResult(
                            pid=pid,
                            name=raw_name,
                            success=True,
                            error_message=""
                        ))
                    except psutil.NoSuchProcess:
                        results.append(KillResult(
                            pid=pid,
                            name=raw_name,
                            success=True,
                            error_message="Processo já encerrado antes do comando."
                        ))
                    except psutil.AccessDenied:
                        results.append(KillResult(
                            pid=pid,
                            name=raw_name,
                            success=False,
                            error_message="Permissão insuficiente. Execute como Administrador se necessário."
                        ))
                    except Exception as ex:
                        results.append(KillResult(
                            pid=pid,
                            name=raw_name,
                            success=False,
                            error_message=str(ex)
                        ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return results
