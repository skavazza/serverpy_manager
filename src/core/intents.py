"""Bounded execution of administrator-authorized shell commands."""

import locale
import subprocess
import threading
import time

import psutil

INTENT_TIMEOUT = 15
INTENT_OUTPUT_LIMIT = 1024 * 1024


class IntentLimitError(Exception):
    pass


def _terminate(process):
    # Descendants are best effort: this is a resource guard, not a sandbox.
    try:
        children = psutil.Process(process.pid).children(recursive=True)
    except psutil.Error:
        children = []
    for child in reversed(children):
        try:
            child.kill()
        except psutil.Error:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def run_intent(command, timeout=INTENT_TIMEOUT, output_limit=INTENT_OUTPUT_LIMIT):
    """Keep the existing shell syntax, with a combined stdout/stderr budget."""
    process = subprocess.Popen(command, shell=True, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    streams = [bytearray(), bytearray()]
    lock = threading.Lock()
    exceeded = threading.Event()
    consumed = 0

    def read_output(pipe, destination):
        nonlocal consumed
        try:
            while True:
                chunk = pipe.read1(8192)
                if not chunk:
                    break
                with lock:
                    available = max(0, output_limit - consumed)
                    destination.extend(chunk[:available])
                    consumed += len(chunk)
                    if consumed > output_limit:
                        exceeded.set()
                        break
        finally:
            pipe.close()

    readers = [threading.Thread(target=read_output, args=(pipe, output), daemon=True)
               for pipe, output in zip((process.stdout, process.stderr), streams)]
    deadline = time.monotonic() + timeout
    try:
        for reader in readers:
            reader.start()
        while process.poll() is None or any(reader.is_alive() for reader in readers):
            if exceeded.is_set():
                raise IntentLimitError('Command output exceeded the 1 MiB limit.')
            if time.monotonic() >= deadline:
                raise IntentLimitError('Command execution timed out.')
            time.sleep(0.01)
        if exceeded.is_set():
            raise IntentLimitError('Command output exceeded the 1 MiB limit.')
        encoding = locale.getpreferredencoding(False)
        return dict(stdout=streams[0].decode(encoding, errors='replace'),
                    stderr=streams[1].decode(encoding, errors='replace'),
                    returncode=process.returncode)
    finally:
        _terminate(process)
        for reader in readers:
            reader.join(timeout=0.5)
