import sys
import argparse
from vendor.systemram.core.privileges import is_admin
from vendor.systemram.core.memory_collector import get_memory_summary, get_priority_breakdown
from vendor.systemram.core.memory_actions import (
    empty_working_sets,
    empty_system_working_set,
    empty_modified_page_list,
    empty_standby_list,
    empty_all,
)

def parse_args(args=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="PyRAMMap",
        description="PyRAMMap - Análise e Otimização da Memória Física do Windows (Sysinternals RAMMap clone)",
    )
    parser.add_argument(
        "-s", "--status",
        action="store_true",
        help="Exibe o resumo detalhado da memória física e de paginação no terminal.",
    )
    parser.add_argument(
        "-Ew", "--empty-working-sets",
        action="store_true",
        help="Esvazia o working set de todos os processos.",
    )
    parser.add_argument(
        "-Es", "--empty-standby",
        action="store_true",
        help="Esvazia toda a Standby List (todas as prioridades).",
    )
    parser.add_argument(
        "-E0", "--empty-standby0",
        action="store_true",
        help="Esvazia apenas a Standby List de Prioridade 0.",
    )
    parser.add_argument(
        "-Em", "--empty-modified",
        action="store_true",
        help="Grava em disco e esvazia a Modified Page List.",
    )
    parser.add_argument(
        "-Ec", "--empty-system-cache",
        action="store_true",
        help="Esvazia o System Working Set (cache de arquivos do sistema).",
    )
    parser.add_argument(
        "-Ea", "--empty-all",
        action="store_true",
        help="Executa todas as ações de esvaziamento em sequência.",
    )

    return parser.parse_args(args)

def print_memory_status():
    summary = get_memory_summary()
    priorities = get_priority_breakdown()

    admin_str = "[ADMINISTRADOR]" if is_admin() else "[SOMENTE LEITURA - NÃO ELEVADO]"
    print("=" * 64)
    print(f" PyRAMMap - Status de Uso de Memória Física {admin_str}")
    print("=" * 64)
    print(f" Total de RAM Física : {summary.total_gb:>8.2f} GB ({summary.total_mb:>10.1f} MB)")
    print(f" Memória em Uso      : {summary.in_use_mb:>8.1f} MB ({summary.load_percent:.1f}%)")
    print(f" Standby (Cache)     : {summary.standby_mb:>8.1f} MB")
    print(f" Modificada          : {summary.modified_mb:>8.1f} MB")
    print(f" Livre / Zerada      : {(summary.free_mb + (summary.zeroed_bytes / (1024*1024))):>8.1f} MB")
    print(f" Cache do Sistema    : {(summary.system_cache_bytes / (1024*1024)):>8.1f} MB")
    print(f" Pool Paginável      : {(summary.paged_pool_bytes / (1024*1024)):>8.1f} MB")
    print(f" Pool Não-Paginável  : {(summary.nonpaged_pool_bytes / (1024*1024)):>8.1f} MB")
    print("-" * 64)
    print(" Detalhamento Standby List por Prioridade:")
    for item in priorities:
        p = item["priority"]
        mb = item["mb"]
        pct = item["percent"]
        bar = "#" * int(pct / 5)
        print(f"   Prioridade {p} : {mb:>8.1f} MB ({pct:>5.1f}%) | {bar}")
    print("=" * 64)

def run_cli(args: argparse.Namespace) -> int:
    has_action = False
    exit_code = 0

    if args.empty_all:
        has_action = True
        print("[*] Executando esvaziamento completo...")
        results = empty_all()
        for k, (ok, msg) in results.items():
            status = "[OK]" if ok else "[ERRO]"
            print(f"  {status} {k}: {msg}")
            if not ok:
                exit_code = 1

    if args.empty_working_sets:
        has_action = True
        ok, msg, _ = empty_working_sets()
        print(f"[{'OK' if ok else 'ERRO'}] {msg}")
        if not ok:
            exit_code = 1

    if args.empty_system_cache:
        has_action = True
        ok, msg = empty_system_working_set()
        print(f"[{'OK' if ok else 'ERRO'}] {msg}")
        if not ok:
            exit_code = 1

    if args.empty_modified:
        has_action = True
        ok, msg = empty_modified_page_list()
        print(f"[{'OK' if ok else 'ERRO'}] {msg}")
        if not ok:
            exit_code = 1

    if args.empty_standby:
        has_action = True
        ok, msg = empty_standby_list(priority0_only=False)
        print(f"[{'OK' if ok else 'ERRO'}] {msg}")
        if not ok:
            exit_code = 1

    if args.empty_standby0:
        has_action = True
        ok, msg = empty_standby_list(priority0_only=True)
        print(f"[{'OK' if ok else 'ERRO'}] {msg}")
        if not ok:
            exit_code = 1

    if args.status or not has_action:
        print_memory_status()

    return exit_code

if __name__ == "__main__":
    cli_args = parse_args()
    sys.exit(run_cli(cli_args))
