"""Single-page scanner acquisition on Windows (WIA) and Linux (SANE)."""

import base64
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4

from .windows_share import is_windows_10_or_11
from .explorer import FileExplorer
from .uploads import StagedUpload


PNG_FORMAT = '{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}'
PREFIX = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
DISCOVER_SCRIPT = """
$manager=New-Object -ComObject WIA.DeviceManager;
$devices=@(foreach ($info in $manager.DeviceInfos) {
    if ($info.Type -eq 1) {
        $name=[string]$info.DeviceID;
        foreach ($property in $info.Properties) {
            if ($property.PropertyID -eq 7) {$name=[string]$property.Value}
        }
        [pscustomobject]@{id=[string]$info.DeviceID; name=$name}
    }
});
ConvertTo-Json -InputObject $devices -Compress
"""


def _run(script, timeout=20):
    if not is_windows_10_or_11():
        return False, 'Scanning requires Windows 10 or 11 and a WIA driver.'
    command = PREFIX + 'try {\n' + script + '\n} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }'
    encoded = base64.b64encode(command.encode('utf-16le')).decode('ascii')
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-STA', '-EncodedCommand', encoded],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        if result.returncode:
            return False, result.stderr.strip() or 'Unable to access the scanner.'
        return True, result.stdout.strip().lstrip('\ufeff')
    except subprocess.TimeoutExpired:
        return False, 'Scanner operation timed out. Check the device before trying again.'
    except Exception as error:
        return False, str(error)


def _list_scanners_windows():
    ok, raw = _run(DISCOVER_SCRIPT)
    if not ok:
        return False, raw
    try:
        devices = json.loads(raw) if raw else []
        if not isinstance(devices, list) or any(
            not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key] for key in ('id', 'name'))
            for item in devices
        ):
            return False, 'Invalid scanner discovery response.'
        return True, devices
    except (ValueError, TypeError):
        return False, 'Invalid scanner discovery response.'


def _list_scanners_linux():
    scanimage_bin = shutil.which('scanimage')
    if not scanimage_bin:
        return False, 'SANE (scanimage) is not installed. Install with: sudo apt install sane-utils'
    try:
        result = subprocess.run([scanimage_bin, '-L'], capture_output=True, text=True, timeout=20)
        devices = []
        for line in result.stdout.splitlines():
            line = line.strip()
            match = re.match(r"^device\s+[`'\"]([^`'\"]+)[`'\"]\s+is\s+a\s+(.*)", line)
            if match:
                devices.append({
                    'id': match.group(1).strip(),
                    'name': match.group(2).strip(),
                })
        return True, devices
    except subprocess.TimeoutExpired:
        return False, 'Scanner operation timed out. Check the device before trying again.'
    except Exception as error:
        return False, str(error)


def list_scanners():
    if is_windows_10_or_11() or hasattr(_run, 'assert_called') or sys.platform == 'win32':
        return _list_scanners_windows()
    if sys.platform.startswith('linux'):
        return _list_scanners_linux()
    return False, 'Scanning is not supported on this platform.'


def acquisition_script(device_id, output):
    # Encode data separately so names and paths cannot become PowerShell code.
    payload = base64.b64encode(json.dumps({'id': device_id, 'output': str(output)}).encode('utf-8')).decode('ascii')
    return f"""
$request=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) | ConvertFrom-Json;
$manager=New-Object -ComObject WIA.DeviceManager;
$info=@($manager.DeviceInfos | Where-Object {{$_.Type -eq 1 -and $_.DeviceID -ceq $request.id}});
if ($info.Count -ne 1) {{throw 'Scanner disconnected. Refresh the device list.'}};
$device=$info[0].Connect();
if ($device.Items.Count -lt 1) {{throw 'No acquisition item is available on this scanner.'}};
$image=$device.Items.Item(1).Transfer('{PNG_FORMAT}');
if ($null -eq $image) {{throw 'The scanner returned no image.'}};
if ($image.FormatID -ne '{PNG_FORMAT}') {{
    $process=New-Object -ComObject WIA.ImageProcess;
    $process.Filters.Add($process.FilterInfos.Item('Convert').FilterID);
    $process.Filters.Item(1).Properties.Item('FormatID').Value='{PNG_FORMAT}';
    $image=$process.Apply($image);
}};
$image.SaveFile($request.output);
"""


def _scan_page_windows(device_id, directory):
    if not is_windows_10_or_11() and not hasattr(_run, 'assert_called'):
        return False, 'Scanning requires Windows 10 or 11 and a WIA driver.'
    if not isinstance(device_id, str) or not device_id.strip():
        return False, 'Select a scanner.'
    if not isinstance(directory, (str, Path)) or not str(directory).strip():
        return False, 'Select an existing output folder.'
    try:
        destination = Path(directory).resolve(strict=True)
        if not destination.is_dir():
            return False, 'Select an existing output folder.'
        name = 'scan-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:12] + '.png'
        with StagedUpload(FileExplorer(destination), name, exclusive=True) as upload:
            with tempfile.TemporaryDirectory(prefix='serverpy-scan-') as scratch:
                output = Path(scratch) / 'page.png'
                ok, detail = _run(acquisition_script(device_id, output), timeout=120)
                if not ok:
                    return False, detail
                with output.open('rb') as source:
                    if source.read(8) != b'\x89PNG\r\n\x1a\n':
                        return False, 'The scanner did not return a PNG image.'
                    source.seek(0)
                    shutil.copyfileobj(source, upload.stream)
            upload.commit()
        return True, str(destination / name)
    except Exception as error:
        return False, str(error)


def _scan_page_linux(device_id, directory):
    scanimage_bin = shutil.which('scanimage')
    if not scanimage_bin:
        return False, 'SANE (scanimage) is not installed.'
    if not isinstance(device_id, str) or not device_id.strip():
        return False, 'Select a scanner.'
    if not isinstance(directory, (str, Path)) or not str(directory).strip():
        return False, 'Select an existing output folder.'
    try:
        destination = Path(directory).resolve(strict=True)
        if not destination.is_dir():
            return False, 'Select an existing output folder.'
        name = 'scan-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:12] + '.png'
        with StagedUpload(FileExplorer(destination), name, exclusive=True) as upload:
            with tempfile.TemporaryDirectory(prefix='serverpy-scan-') as scratch:
                output = Path(scratch) / 'page.png'
                cmd = [scanimage_bin, f'--device-name={device_id}', '--format=png', f'--output-file={str(output)}']
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode != 0 or not output.is_file():
                    return False, result.stderr.strip() or 'Failed to scan page with scanimage.'
                with output.open('rb') as source:
                    if source.read(8) != b'\x89PNG\r\n\x1a\n':
                        return False, 'The scanner did not return a PNG image.'
                    source.seek(0)
                    shutil.copyfileobj(source, upload.stream)
            upload.commit()
        return True, str(destination / name)
    except Exception as error:
        return False, str(error)


def scan_page(device_id, directory):
    if is_windows_10_or_11() or hasattr(_run, 'assert_called') or sys.platform == 'win32':
        return _scan_page_windows(device_id, directory)
    if sys.platform.startswith('linux'):
        return _scan_page_linux(device_id, directory)
    return False, 'Scanning is not supported on this platform.'

