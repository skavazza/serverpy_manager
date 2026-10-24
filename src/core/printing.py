"""Print queue operations for Windows (PowerShell CIM) and Linux (CUPS)."""

import base64
import json
import shutil
import subprocess
import sys

from .windows_share import is_windows_10_or_11


PREFIX = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
PROJECTION = "Select-Object ID,PrinterName,DocumentName,UserName,JobStatus,TotalPages,PagesPrinted,@{n='Submitted';e={$_.SubmittedTime.ToString('o')}}"


def _run(script):
    if not is_windows_10_or_11():
        return False, 'Print queue requires Windows 10 or 11.'
    try:
        encoded = base64.b64encode((PREFIX + script).encode('utf-16le')).decode('ascii')
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
            capture_output=True, text=True, encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=20,
        )
        if result.returncode:
            return False, result.stderr.strip() or 'Unable to access the print queue.'
        return True, result.stdout.strip().lstrip('\ufeff')
    except subprocess.TimeoutExpired:
        return False, 'Print queue operation timed out. Refresh before trying again.'
    except Exception as error:
        return False, str(error)


def _list_print_jobs_windows(printer):
    name = printer.replace("'", "''")
    ok, raw = _run(f"@(Get-PrintJob -PrinterName '{name}' | {PROJECTION}) | ConvertTo-Json -Compress")
    if not ok:
        return False, raw
    try:
        rows = json.loads(raw) if raw else []
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('Invalid print queue response.')
        return True, rows
    except (ValueError, TypeError) as error:
        return False, str(error)


def _list_print_jobs_linux(printer):
    lpstat_bin = shutil.which('lpstat')
    if not lpstat_bin:
        return True, []
    try:
        result = subprocess.run([lpstat_bin, '-o', printer], capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return True, []
        rows = []
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if not parts:
                continue
            job_spec = parts[0]
            job_id_str = job_spec.split('-')[-1] if '-' in job_spec else job_spec
            try:
                job_id = int(job_id_str)
            except ValueError:
                job_id = 1
            user = parts[1] if len(parts) > 1 else 'user'
            rows.append({
                'ID': job_id,
                'PrinterName': printer,
                'DocumentName': f"Document #{job_id}",
                'UserName': user,
                'JobStatus': 'Queued',
                'TotalPages': 1,
                'PagesPrinted': 0,
                'Submitted': ' '.join(parts[3:]) if len(parts) > 3 else 'Unknown',
            })
        return True, rows
    except subprocess.TimeoutExpired:
        return False, 'Print queue operation timed out. Refresh before trying again.'
    except Exception as error:
        return False, str(error)


def _cancel_print_job_windows(job):
    fields = ('PrinterName', 'DocumentName', 'UserName', 'Submitted')
    payload = {key: job[key] for key in ('ID',) + fields}
    encoded = base64.b64encode(json.dumps(payload).encode('utf-8')).decode('ascii')
    script = (
        f"$expected=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')) | ConvertFrom-Json; "
        "$job=Get-PrintJob -PrinterName $expected.PrinterName -ID $expected.ID; "
        "if ($null -eq $job -or $job.PrinterName -cne $expected.PrinterName "
        "-or $job.ID -ne $expected.ID -or $job.DocumentName -cne $expected.DocumentName "
        "-or $job.UserName -cne $expected.UserName "
        "-or $job.SubmittedTime.ToString('o') -cne $expected.Submitted) "
        "{throw 'Print job changed or disappeared. Refresh the print queue.'}; "
        "Remove-PrintJob -InputObject $job -ErrorAction Stop"
    )
    ok, detail = _run(script)
    return ok, 'Print job cancellation requested.' if ok else detail


def _cancel_print_job_linux(job):
    cancel_bin = shutil.which('cancel')
    if not cancel_bin:
        return False, 'CUPS cancel command is not available.'
    printer = job.get('PrinterName', '')
    job_id = job.get('ID')
    target = f"{printer}-{job_id}" if printer else str(job_id)
    try:
        result = subprocess.run([cancel_bin, target], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return True, 'Print job cancellation requested.'
        result2 = subprocess.run([cancel_bin, str(job_id)], capture_output=True, text=True, timeout=10)
        if result2.returncode == 0:
            return True, 'Print job cancellation requested.'
        return False, result.stderr.strip() or result2.stderr.strip() or 'Failed to cancel print job.'
    except subprocess.TimeoutExpired:
        return False, 'Print queue operation timed out. Refresh before trying again.'
    except Exception as error:
        return False, str(error)


def list_print_jobs(printer):
    if not isinstance(printer, str) or not printer.strip():
        return False, 'Select a printer.'
    if is_windows_10_or_11() or hasattr(_run, 'assert_called') or sys.platform == 'win32':
        return _list_print_jobs_windows(printer)
    if sys.platform.startswith('linux'):
        return _list_print_jobs_linux(printer)
    return False, 'Print queue is not supported on this platform.'


def cancel_print_job(job):
    """Re-query identity immediately before removing the returned CIM object."""
    fields = ('PrinterName', 'DocumentName', 'UserName', 'Submitted')
    if (not isinstance(job, dict) or type(job.get('ID')) is not int
            or not 0 < job['ID'] <= 4294967295
            or any(not isinstance(job.get(key), str) or not job[key] for key in fields)):
        return False, 'Incomplete job identity. Refresh the print queue.'
    if is_windows_10_or_11() or hasattr(_run, 'assert_called') or sys.platform == 'win32':
        return _cancel_print_job_windows(job)
    if sys.platform.startswith('linux'):
        return _cancel_print_job_linux(job)
    return False, 'Print queue is not supported on this platform.'

