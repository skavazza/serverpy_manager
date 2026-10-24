"""Helpers for Secure Shell (SSH) connections and validation."""

import re
import shutil
import socket
import stat
import subprocess
from pathlib import Path

import paramiko

_SSH_TARGET_RE = re.compile(r"^(?:[A-Za-z0-9._-]+@)?(?:[A-Za-z0-9.-]+|(?:\d{1,3}\.){3}\d{1,3}|\[[0-9A-Fa-f:]+\])$")


def ssh_client_path():
    for candidate in ('ssh', 'ssh.exe'):
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _identity_options(identity_file):
    if not identity_file:
        return []
    path = Path(identity_file).expanduser()
    if not path.is_file():
        raise FileNotFoundError('The SSH identity file does not exist or is not a file.')
    return ['-i', str(path), '-o', 'IdentitiesOnly=yes']


def _quote_sftp_path(path):
    value = str(path)
    if not value or any(character in value for character in ('\0', '\n', '\r')):
        raise ValueError('Enter a valid SFTP file path without line breaks.')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _password_client(host, username, port, password, timeout):
    if not username or not str(username).strip():
        raise ValueError('Enter a username to use password authentication.')
    if not password:
        raise ValueError('Enter the SSH password.')
    username, target, port_value = validate_ssh_target(host, username, port)
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(
            hostname=target, port=port_value, username=username, password=password,
            timeout=timeout, auth_timeout=timeout, banner_timeout=timeout,
            allow_agent=False, look_for_keys=False,
        )
    except paramiko.BadHostKeyException as error:
        client.close()
        raise OSError(
            'The SSH host key changed. Verify the server identity before updating known_hosts.'
        ) from error
    except paramiko.SSHException as error:
        client.close()
        if 'not found in known_hosts' in str(error).lower():
            raise OSError(
                'The SSH host key is not trusted yet. Connect once with OpenSSH to verify and save it.'
            ) from error
        raise OSError(str(error)) from error
    except (OSError, socket.timeout):
        client.close()
        raise
    return client


def _password_ssh_check(host, username, port, timeout, password):
    client = _password_client(host, username, port, password, timeout)
    try:
        _stdin, stdout, _stderr = client.exec_command('echo __SSH_OK__', timeout=timeout)
        if '__SSH_OK__' in stdout.read().decode(errors='replace'):
            return True, 'SSH connection is available.'
        return False, 'SSH connection failed.'
    except paramiko.SSHException as error:
        raise OSError(str(error)) from error
    finally:
        client.close()


def _password_run_command(host, username, port, command, timeout, password):
    client = _password_client(host, username, port, password, min(timeout, 15))
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        output = stdout.read().decode(errors='replace').strip()
        error = stderr.read().decode(errors='replace').strip()
        status = stdout.channel.recv_exit_status()
        if status == 0:
            return True, output or 'Command completed successfully.'
        return False, error or output or 'Remote command failed.'
    except paramiko.SSHException as error:
        raise OSError(str(error)) from error
    finally:
        client.close()


def validate_ssh_target(host, username=None, port=22):
    value = (host or '').strip()
    if not value:
        raise ValueError('Enter a host name, IP address or SSH target.')
    if '@' in value and value.count('@') == 1:
        candidate_user, remainder = value.split('@', 1)
        if candidate_user and remainder:
            username = candidate_user
            value = remainder
    value = value.strip().strip('[]')
    if not _SSH_TARGET_RE.fullmatch(f"{username + '@' if username else ''}{value}"):
        raise ValueError('The SSH host is invalid. Use only a hostname, IPv4 address or bracketed IPv6 literal.')
    try:
        port_value = int(port)
    except (TypeError, ValueError) as error:
        raise ValueError('The SSH port must be a number between 1 and 65535.') from error
    if not 1 <= port_value <= 65535:
        raise ValueError('The SSH port must be a number between 1 and 65535.')
    return username, value, port_value


def build_sftp_transfer(host, username, port, identity_file, direction, local_path, remote_path):
    if direction not in ('upload', 'download'):
        raise ValueError('Choose upload or download for the SFTP transfer.')
    local_file = Path(local_path).expanduser()
    if direction == 'upload' and not local_file.is_file():
        raise FileNotFoundError('Select an existing local file to upload.')
    if direction == 'download' and not local_file.parent.is_dir():
        raise FileNotFoundError('The local download folder does not exist.')
    username, target, port_value = validate_ssh_target(host, username, port)
    client = shutil.which('sftp') or shutil.which('sftp.exe')
    if not client:
        raise FileNotFoundError('OpenSSH SFTP is not installed or not available on this system.')
    remote = _quote_sftp_path(remote_path)
    local = _quote_sftp_path(str(local_file))
    transfer = f'put {local} {remote}' if direction == 'upload' else f'get {remote} {local}'
    args = [
        client, '-b', '-', '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=accept-new', '-P', str(port_value),
    ]
    args.extend(_identity_options(identity_file))
    args.append(f'{username}@{target}' if username else target)
    return args, transfer + '\n'


def list_sftp_directory(
    host, username, port, identity_file, remote_path, timeout=20,
    auth_method='key', password=None,
):
    path = str(remote_path or '/').strip() or '/'
    if any(character in path for character in ('\0', '\n', '\r')):
        raise ValueError('Enter a valid SFTP file path without line breaks.')
    if auth_method == 'password':
        client = _password_client(host, username, port, password, timeout)
        try:
            with client.open_sftp() as sftp:
                entries = [
                    {'name': entry.filename, 'is_dir': stat.S_ISDIR(entry.st_mode)}
                    for entry in sftp.listdir_attr(path)
                    if entry.filename not in ('.', '..')
                ]
            return sorted(entries, key=lambda entry: (not entry['is_dir'], entry['name'].casefold()))
        except paramiko.SSHException as error:
            raise OSError(str(error)) from error
        finally:
            client.close()
    username, target, port_value = validate_ssh_target(host, username, port)
    client = shutil.which('sftp') or shutil.which('sftp.exe')
    if not client:
        raise FileNotFoundError('OpenSSH SFTP is not installed or not available on this system.')
    command = [
        client, '-b', '-', '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=accept-new', '-P', str(port_value),
    ]
    command.extend(_identity_options(identity_file))
    command.append(f'{username}@{target}' if username else target)
    try:
        result = subprocess.run(
            command, input=f'ls -la {_quote_sftp_path(path)}\n',
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError('SFTP directory listing timed out.') from error
    if result.returncode:
        raise OSError((result.stderr or result.stdout or 'Unable to list the remote directory.').strip())
    entries = []
    for line in result.stdout.splitlines():
        if line.startswith('total '):
            continue
        match = re.match(
            r'^([bcdlps-][rwxStTs-]{9})\s+\d+\s+\S+\s+\S+\s+\d+\s+'
            r'\S+\s+\d{1,2}\s+(?:\d{2}:\d{2}|\d{4})\s+(.+)$',
            line,
        )
        if not match:
            continue
        name = match.group(2)
        if name in ('.', '..'):
            continue
        entries.append({'name': name, 'is_dir': match.group(1).startswith('d')})
    if result.stdout.strip() and not entries:
        raise OSError('The remote SFTP directory listing used an unsupported format.')
    return sorted(entries, key=lambda entry: (not entry['is_dir'], entry['name'].casefold()))


class SFTPTransferCancelled(Exception):
    pass


def sftp_transfer_with_password(
    host, username, port, password, direction, local_path, remote_path,
    cancelled, progress,
):
    if direction not in ('upload', 'download'):
        raise ValueError('Choose upload or download for the SFTP transfer.')
    local_file = Path(local_path).expanduser()
    if direction == 'upload' and not local_file.is_file():
        raise FileNotFoundError('Select an existing local file to upload.')
    if direction == 'download' and not local_file.parent.is_dir():
        raise FileNotFoundError('The local download folder does not exist.')
    remote = str(remote_path)
    if not remote or any(character in remote for character in ('\0', '\n', '\r')):
        raise ValueError('Enter a valid SFTP file path without line breaks.')
    client = _password_client(host, username, port, password, 15)
    try:
        with client.open_sftp() as sftp:
            def report(transferred, total):
                progress(transferred, total)
                if cancelled.is_set():
                    raise SFTPTransferCancelled('SFTP transfer cancelled.')

            if direction == 'upload':
                sftp.put(str(local_file), remote, callback=report)
            else:
                sftp.get(remote, str(local_file), callback=report)
            if cancelled.is_set():
                raise SFTPTransferCancelled('SFTP transfer cancelled.')
    except paramiko.SSHException as error:
        raise OSError(str(error)) from error
    finally:
        client.close()


def build_ssh_command(host, username=None, port=22, command=None, identity_file=None):
    username, target, port_value = validate_ssh_target(host, username, port)
    client = ssh_client_path()
    if not client:
        raise FileNotFoundError('OpenSSH is not installed or not available on this system.')
    args = [client, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=5', '-p', str(port_value)]
    args.extend(_identity_options(identity_file))
    remote_target = f'{username}@{target}' if username else target
    args.append(remote_target)
    if command:
        args.append(command)
    return args


def ssh_check_connection(
    host, username=None, port=22, timeout=5, identity_file=None,
    auth_method='key', password=None,
):
    if auth_method == 'password':
        try:
            return _password_ssh_check(host, username, port, timeout, password)
        except (OSError, socket.timeout, ValueError) as error:
            return False, str(error)
    client = ssh_client_path()
    if not client:
        return False, 'OpenSSH is not installed or not available on this system.'
    try:
        username, target, port_value = validate_ssh_target(host, username, port)
    except ValueError as error:
        return False, str(error)
    command = [client, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new', '-o', f'ConnectTimeout={timeout}', '-p', str(port_value)]
    try:
        command.extend(_identity_options(identity_file))
    except FileNotFoundError as error:
        return False, str(error)
    command.extend([f'{username}@{target}' if username else target, 'echo', '__SSH_OK__'])
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=max(timeout + 5, 10), check=False)
    except subprocess.TimeoutExpired:
        return False, 'SSH connection timed out.'
    except OSError as error:
        return False, str(error)
    if result.returncode == 0 and '__SSH_OK__' in result.stdout:
        return True, 'SSH connection is available.'
    message = (result.stderr or result.stdout or 'SSH connection failed.').strip()
    return False, message or 'SSH connection failed.'


def ssh_run_command(
    host, username=None, port=22, command=None, timeout=30, identity_file=None,
    auth_method='key', password=None,
):
    if not command or not str(command).strip():
        raise ValueError('Enter a command to run on the remote host.')
    if auth_method == 'password':
        return _password_run_command(host, username, port, str(command), timeout, password)
    client = ssh_client_path()
    if not client:
        raise FileNotFoundError('OpenSSH is not installed or not available on this system.')
    username, target, port_value = validate_ssh_target(host, username, port)
    args = [client, '-o', 'StrictHostKeyChecking=accept-new', '-o', 'BatchMode=yes', '-p', str(port_value)]
    args.extend(_identity_options(identity_file))
    if username:
        args.extend(['-l', username])
    args.extend([target, str(command)])
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise TimeoutError('SSH command timed out.') from error
    if result.returncode == 0:
        return True, result.stdout.strip() or 'Command completed successfully.'
    error_text = (result.stderr or result.stdout or 'Remote command failed.').strip()
    return False, error_text or 'Remote command failed.'


def ssh_open_terminal(host, username=None, port=22, identity_file=None, auth_method='key'):
    username, target, port_value = validate_ssh_target(host, username, port)
    client = ssh_client_path()
    if not client:
        raise FileNotFoundError('OpenSSH is not installed or not available on this system.')
    host_key_policy = 'ask' if auth_method == 'password' else 'accept-new'
    args = [client, '-o', f'StrictHostKeyChecking={host_key_policy}', '-p', str(port_value), f'{username}@{target}' if username else target]
    if auth_method == 'password':
        args[-1:-1] = [
            '-o', 'PreferredAuthentications=password,keyboard-interactive',
            '-o', 'PubkeyAuthentication=no',
        ]
    else:
        args[-1:-1] = _identity_options(identity_file)
    return subprocess.Popen(args)
