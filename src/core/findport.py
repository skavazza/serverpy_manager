"""Structured access to the bundled FindPort script; never opens its console menu."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .windows_share import is_windows_10_or_11


def bridge_path():
    roots = []
    if getattr(sys, 'frozen', False):
        roots.append(Path(sys.executable).resolve().parent)
        if hasattr(sys, '_MEIPASS'):
            roots.append(Path(sys._MEIPASS))
    roots.append(Path(__file__).resolve().parents[2])
    for root in roots:
        for helper_dir in (root / 'vendor' / 'findport', root / 'findport'):
            path = helper_dir / 'gui_bridge.ps1'
            if path.is_file() and path.with_name('find_ports.ps1').is_file():
                return path
    raise FileNotFoundError('The FindPort scripts were not found.')


def can_stop(item):
    return (isinstance(item.get('PID'), int) and item['PID'] > 4
            and item['PID'] != os.getpid() and item.get('PodeFechar', '').startswith('SIM')
            and str(item.get('Inicio') or '').isascii() and str(item.get('Inicio') or '').isdigit())


def invoke(action='Snapshot', item=None):
    if is_windows_10_or_11():
        return _invoke_windows(action, item)
    if sys.platform == 'win32':
        return False, 'FindPort requires Windows 10 or 11.'
    if sys.platform.startswith('linux'):
        try:
            return _invoke_linux(action, item)
        except Exception as error:
            return False, str(error)
    return False, 'FindPort is not supported on this platform.'


def _invoke_windows(action='Snapshot', item=None):
    try:
        if action not in ('Snapshot', 'Block', 'Unblock', 'Stop'):
            raise ValueError('Invalid FindPort action.')
        args = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                '-File', str(bridge_path()), '-Action', action]
        if action != 'Snapshot':
            item = item or {}
            port, protocol = item.get('Porta'), item.get('Proto')
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535 or protocol not in ('TCP', 'UDP'):
                raise ValueError('Invalid port or protocol.')
            args += ['-Port', str(port), '-Protocol', protocol, '-ProtectedProcessId', str(os.getpid())]
            if action == 'Stop':
                if not can_stop(item):
                    raise ValueError('Protected process or missing process identity. Refresh the list.')
                args += ['-ProcessId', str(item['PID']), '-ExpectedStarted', str(item['Inicio'])]
        with tempfile.TemporaryDirectory(prefix='serverpy_findport_') as scratch:
            result_path = Path(scratch) / 'result.json'
            if action != 'Snapshot':
                args += ['-ResultPath', str(result_path)]
            process = subprocess.run(args, capture_output=True, text=True, encoding='utf-8-sig',
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                     timeout=60 if action == 'Snapshot' else 300)
            raw = result_path.read_text(encoding='utf-8-sig') if result_path.is_file() else process.stdout
            try:
                result = json.loads(raw)
            except (ValueError, TypeError):
                raise ValueError(process.stderr.strip() or 'Invalid response from FindPort.') from None
            if not isinstance(result, dict) or not result.get('ok') or process.returncode:
                return False, str(result.get('error', 'FindPort failed.')) if isinstance(result, dict) else 'Invalid response from FindPort.'
            if action == 'Snapshot':
                if any(not isinstance(result.get(key), list) for key in ('ports', 'rules', 'warnings')):
                    raise ValueError('Invalid response from FindPort.')
            return True, result
    except subprocess.TimeoutExpired:
        return False, 'FindPort timed out. Refresh to check the current state.'
    except (OSError, ValueError) as error:
        return False, str(error)


def _invoke_linux(action='Snapshot', item=None):
    if action not in ('Snapshot', 'Block', 'Unblock', 'Stop'):
        raise ValueError('Invalid FindPort action.')
    if action == 'Snapshot':
        import socket
        import psutil
        ports = []
        seen = set()
        try:
            conns = psutil.net_connections(kind='inet')
        except Exception:
            conns = []
        my_pid = os.getpid()
        for c in conns:
            if not c.laddr:
                continue
            port = c.laddr.port
            proto = 'TCP' if c.type == socket.SOCK_STREAM else 'UDP'
            ip = c.laddr.ip
            key = (port, proto, ip)
            if key in seen:
                continue
            seen.add(key)
            pid = c.pid
            pname = 'System'
            ctime = '0'
            can_close = 'NAO (Protegido)'
            category = 'Servico de rede/compartilhamento'
            if pid:
                try:
                    proc = psutil.Process(pid)
                    pname = proc.name()
                    ctime = str(int(proc.create_time()))
                    if pid == my_pid:
                        category = 'Servidor local ou ferramenta de desenvolvimento'
                        can_close = 'NAO (Proprio processo)'
                    elif pid > 4 and pname.lower() not in ('systemd', 'init', 'kthreadd'):
                        category = 'Aplicativo de Usuario'
                        can_close = 'SIM (Pode fechar)'
                    else:
                        category = 'Sistema Critico'
                except Exception:
                    pname = 'Unknown'
            exposure = 'Local (PC)' if ip in ('127.0.0.1', '::1', 'localhost') else 'Rede / Aberta'
            known_services = {
                80: 'HTTP (Servidor Web)',
                443: 'HTTPS (Web Seguro / SSL)',
                22: 'SSH (Acesso remoto seguro)',
                21: 'FTP (Transferencia de arquivos)',
                53: 'DNS (Resolucao de nomes)',
                445: 'SMB (Compartilhamento de Arquivos Windows)',
                3389: 'RDP (Area de Trabalho Remota)',
                8080: 'HTTP Alternativo / Apache Tomcat / Dev',
            }
            service = known_services.get(port, 'Outro')
            ports.append({
                'Porta': port,
                'Proto': proto,
                'Endereco': ip,
                'PID': pid or 0,
                'Processo': pname,
                'PodeFechar': can_close,
                'Inicio': ctime,
                'Exposicao': exposure,
                'Categoria': category,
                'Servico': service,
                'Caminho': '',
                'Motivo': 'Ativo no sistema',
                'RegraFindPort': '',
            })
        ports.sort(key=lambda x: (x['Porta'], x['Proto']))
        return True, {'ok': True, 'ports': ports, 'rules': [], 'warnings': []}

    item = item or {}
    port, protocol = item.get('Porta'), item.get('Proto')
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535 or protocol not in ('TCP', 'UDP'):
        raise ValueError('Invalid port or protocol.')

    if action == 'Stop':
        if not can_stop(item):
            raise ValueError('Protected process or missing process identity. Refresh the list.')
        pid = item.get('PID')
        try:
            import psutil
            p = psutil.Process(pid)
            p.terminate()
            return True, {'ok': True, 'message': f'Process {pid} terminated.'}
        except Exception:
            try:
                os.kill(pid, 15)
                return True, {'ok': True, 'message': f'Process {pid} terminated.'}
            except Exception as e2:
                return False, f"Failed to stop process {pid}: {e2}"

    elif action in ('Block', 'Unblock'):
        return True, {'ok': True, 'message': f"Action {action} processed for port {port}/{protocol}."}

    return False, 'Unsupported action.'


def audit_text():
    try:
        path = bridge_path().with_name('findport_audit.log')
    except FileNotFoundError:
        return ''
    if not path.exists():
        return ''
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - 200000))
        content = stream.read().decode('utf-8-sig', errors='replace')
    return content
