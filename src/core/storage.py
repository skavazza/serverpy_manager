"""Read-only discovery of mounted USB and removable storage on Windows and Linux."""

import json
import os
import shutil
import subprocess
import sys
import psutil

from .windows_share import is_windows_10_or_11


def _list_external_drives_windows():
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "$usb = @(Get-Disk | Where-Object BusType -eq 'USB' | Get-Partition | "
        "Where-Object DriveLetter | Get-Volume); "
        "$removable = @(Get-Volume | Where-Object DriveType -eq 'Removable'); "
        "@($usb + $removable) | Where-Object DriveLetter | "
        "Sort-Object DriveLetter -Unique | "
        "Select-Object DriveLetter,FileSystemLabel,Size,SizeRemaining | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        if result.returncode:
            return False, result.stderr.strip() or 'Unable to query external drives.'
        data = json.loads(result.stdout.strip() or '[]')
        if data is None:
            data = []
        if isinstance(data, dict):
            data = [data]
        drives = []
        for item in data:
            letter = str(item.get('DriveLetter') or '').upper()
            if len(letter) != 1 or letter not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
                continue
            drives.append({
                'path': letter + ':\\',
                'label': item.get('FileSystemLabel') or '',
                'size': max(0, int(item.get('Size') or 0)),
                'free': max(0, int(item.get('SizeRemaining') or 0)),
            })
        return True, drives
    except subprocess.TimeoutExpired:
        return False, 'Timeout querying external drives. Try refreshing.'
    except (OSError, ValueError, TypeError, AttributeError) as error:
        return False, str(error)


def _list_external_drives_linux():
    try:
        drives = []
        seen_paths = set()

        lsblk_path = shutil.which('lsblk')
        if lsblk_path:
            try:
                res = subprocess.run(
                    [lsblk_path, '-J', '-o', 'NAME,MOUNTPOINT,LABEL,SIZE,FSAVAIL,TRAN,RM'],
                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10
                )
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout).get('blockdevices', [])

                    def process_dev(dev, is_removable=False):
                        rm = dev.get('rm') is True or dev.get('tran') == 'usb' or is_removable
                        mp = dev.get('mountpoint')
                        if mp and rm and os.path.isdir(mp):
                            if mp not in seen_paths:
                                seen_paths.add(mp)
                                try:
                                    usage = psutil.disk_usage(mp)
                                    drives.append({
                                        'path': mp,
                                        'label': dev.get('label') or os.path.basename(mp),
                                        'size': usage.total,
                                        'free': usage.free,
                                    })
                                except Exception:
                                    pass
                        for child in dev.get('children', []):
                            process_dev(child, is_removable=rm)

                    for dev in data:
                        process_dev(dev)
            except Exception:
                pass

        for part in psutil.disk_partitions(all=False):
            mp = part.mountpoint
            if mp in seen_paths:
                continue
            is_media = mp.startswith(('/media/', '/run/media/', '/mnt/'))
            is_usb = 'removable' in part.opts or 'usb' in part.opts
            if (is_media or is_usb) and os.path.isdir(mp):
                seen_paths.add(mp)
                try:
                    usage = psutil.disk_usage(mp)
                    label = os.path.basename(mp) or part.device
                    drives.append({
                        'path': mp,
                        'label': label,
                        'size': usage.total,
                        'free': usage.free,
                    })
                except Exception:
                    pass

        drives.sort(key=lambda d: d['path'])
        return True, drives
    except subprocess.TimeoutExpired:
        return False, 'Timeout querying external drives. Try refreshing.'
    except Exception as error:
        return False, str(error)


def list_external_drives():
    """Return mounted USB volumes, including USB disks reported as fixed disks."""
    if is_windows_10_or_11():
        return _list_external_drives_windows()
    if sys.platform == 'win32':
        return False, 'Drive discovery requires Windows 10 or 11.'
    if sys.platform.startswith('linux'):
        return _list_external_drives_linux()
    return False, 'Drive discovery is not supported on this platform.'

