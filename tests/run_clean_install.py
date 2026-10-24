"""Validate a source snapshot in a new venv, without touching the user's venv."""

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = ('src', 'tests', 'vendor', 'share-folder', 'visual_identity', 'docs',
                'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'ROADMAP.md',
                'requirements.txt', 'constraints.txt', 'setup_env.py', 'start.bat',
                'start.sh', 'server.svg', '.gitattributes')


def main():
    evidence = ROOT / 'artifacts'
    evidence.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='clean-install_', dir=evidence))
    source = run / 'source'
    source.mkdir()
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others',
                                     '--exclude-standard', '--', *SOURCE_PATHS], cwd=ROOT)
    manifest = {}
    for relative in sorted(set(names.decode('utf-8').split('\0')) - {''}):
        origin = ROOT / relative
        if not origin.is_file() or origin.is_symlink():
            continue
        if not origin.resolve().is_relative_to(ROOT):
            raise RuntimeError('Source escapes workspace: ' + relative)
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
        manifest[relative] = hashlib.sha256(destination.read_bytes()).hexdigest()
    (run / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    report = dict(platform=platform.platform(), python=sys.version,
                  source_kind='working-tree snapshot including uncommitted files; not a clean Git clone',
                  base_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
                  files=len(manifest), stages=[])
    environment = dict(os.environ)
    environment.pop('PYTHONHOME', None)
    environment['PYTHONPATH'] = str(source)
    environment['QT_QPA_PLATFORM'] = 'offscreen'
    environment['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
    environment['PYTHONIOENCODING'] = 'utf-8'

    def stage(name, args):
        started = time.monotonic()
        with (run / (name + '.log')).open('wb') as log:
            result = subprocess.run(args, cwd=source, env=environment,
                                    stdout=log, stderr=log, timeout=900)
        log_text = (run / (name + '.log')).read_text(encoding='utf-8', errors='replace')
        background_error = name == 'desktop-smoke' and 'Error calling Python override' in log_text
        report['stages'].append(dict(name=name, exit_code=result.returncode,
                                     background_error=background_error,
                                     seconds=round(time.monotonic() - started, 2)))
        (run / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(name + ': ' + str(result.returncode), flush=True)
        if result.returncode or background_error:
            raise RuntimeError('Validation failed: ' + name + '; see ' + str(run))

    print('Evidence: ' + str(run), flush=True)
    stage('create-venv', [sys.executable, '-m', 'venv', str(source / 'venv')])
    python = source / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    stage('install', [str(python), 'setup_env.py'])
    stage('check', [str(python), 'setup_env.py', '--check'])
    stage('pip-check', [str(python), '-m', 'pip', 'check'])
    stage('freeze', [str(python), '-m', 'pip', 'freeze'])
    if os.name == 'nt':
        stage('launcher-check', ['cmd.exe', '/d', '/c', 'start.bat', '--check'])
    else:
        stage('launcher-check', ['bash', 'start.sh', '--check'])
    stage('desktop-smoke', [str(python), 'tests/run_desktop_smoke.py', str(run / 'desktop')])
    chrome = (shutil.which('chrome') or shutil.which('google-chrome') or shutil.which('chromium'))
    if chrome is None and Path('C:/Program Files/Google/Chrome/Application/chrome.exe').is_file():
        chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
    if chrome and shutil.which('node'):
        environment['PATH'] = str(Path(chrome).parent) + os.pathsep + environment.get('PATH', '')
        stage('web-smoke', [str(python), 'tests/run_web_smoke.py', str(run / 'web')])
        environment['SERVERPY_SMOKE_MOUNT'] = '1'
        stage('web-mounted-smoke', [str(python), 'tests/run_web_smoke.py', str(run / 'web-mounted')])
        environment.pop('SERVERPY_SMOKE_MOUNT', None)
    else:
        report['browser_validation'] = 'not run: Chrome and Node required'
    stage('regression', [str(python), '-m', 'unittest', 'discover', '-s', 'tests', '-q'])
    print('Clean installation and validation passed.', flush=True)


if __name__ == '__main__':
    main()
