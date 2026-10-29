"""Bounded local Ollama lifecycle commands; never execute browser-supplied commands."""
import contextlib
import hashlib
import ipaddress
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

from django.conf import settings

_lock = threading.Lock()
_children = {}


class RuntimeErrorDetail(Exception):
    pass


def local_endpoint():
    try:
        value = urlsplit(settings.OLLAMA_BASE_URL)
    except ValueError:
        raise RuntimeErrorDetail("The configured Ollama endpoint is invalid.")
    try:
        local = value.hostname == 'localhost' or ipaddress.ip_address(value.hostname).is_loopback
    except ValueError:
        local = False
    if not local or value.scheme != 'http' or value.username or value.password or value.path not in ('', '/') or value.query or value.fragment:
        raise RuntimeErrorDetail('Server controls require a local HTTP Ollama endpoint.')
    # Validate the port and normalize localhost to avoid a public bind via inherited settings.
    try:
        port = value.port or 11434
    except ValueError:
        raise RuntimeErrorDetail('The configured Ollama port is invalid.')
    host = '[::1]' if value.hostname == '::1' else '127.0.0.1'
    return f'http://{host}:{port}'


def _paths():
    directory = Path(settings.BASE_DIR) / '.runtime' / 'ollama'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


@contextlib.contextmanager
def _exclusive():
    with _lock, (_paths() / 'control.lock').open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _identity(pid):
    """Include process start time and command to reject stale/reused PIDs."""
    if os.name == 'nt':
        command = ['powershell', '-NoProfile', '-NonInteractive', '-Command',
                   f'Get-CimInstance Win32_Process -Filter "ProcessId = {int(pid)}" | Select-Object CreationDate,ExecutablePath,CommandLine | ConvertTo-Json -Compress']
    else:
        command = ['ps', '-p', str(int(pid)), '-o', 'lstart=', '-o', 'args=']
    result = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
    value = result.stdout.strip()
    return hashlib.sha256(value.encode()).hexdigest() if result.returncode == 0 and value and value != 'null' else None


def _managed(endpoint):
    try:
        state = json.loads((_paths() / 'server.json').read_text())
        pid = int(state['pid'])
        if pid > 1 and state['endpoint'] == endpoint and state['identity'] == _identity(pid):
            child = _children.get(pid)
            if child is None or child.poll() is None:
                return state
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        pass
    return None


def _online(endpoint):
    try:
        with urlopen(endpoint + '/api/version', timeout=.8) as response:
            value = json.loads(response.read(4096))
        return isinstance(value, dict) and isinstance(value.get('version'), str)
    except (OSError, ValueError):
        return False


def server_status():
    endpoint = local_endpoint()
    running = _online(endpoint)
    return {'running': running, 'managed': bool(_managed(endpoint)), 'installed': bool(shutil.which('ollama')),
            'endpoint': endpoint, 'scope': 'This computer · shared by all organizations'}


def change_server(action):
    if action not in ('start', 'stop'):
        raise RuntimeErrorDetail('Choose start or stop.')
    endpoint = local_endpoint()
    try:
        with _exclusive():
            state = _managed(endpoint)
            if action == 'stop':
                if not state:
                    if _online(endpoint):
                        raise RuntimeErrorDetail('Ollama was started outside OrgForms. Quit its app or stop its service there.')
                    return server_status()
                if os.name == 'nt':
                    os.kill(state['pid'], signal.SIGTERM)
                else:
                    # Only our detached process group, after verifying its original process identity.
                    if os.getpgid(state['pid']) != state['pid']:
                        raise RuntimeErrorDetail('The managed process changed. Stop Ollama from its original launcher.')
                    os.killpg(state['pid'], signal.SIGTERM)
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    if not _online(endpoint):
                        child = _children.pop(state['pid'], None)
                        if child:
                            try: child.wait(timeout=2)
                            except subprocess.TimeoutExpired: pass
                        (_paths() / 'server.json').unlink(missing_ok=True)
                        return server_status()
                    time.sleep(.1)
                raise RuntimeErrorDetail('Ollama is still stopping. Refresh its status shortly.')
            if _online(endpoint):
                return server_status()
            if state:
                raise RuntimeErrorDetail('Ollama is starting. Refresh its status shortly.')
            binary = shutil.which('ollama')
            if not binary:
                raise RuntimeErrorDetail('Ollama is not installed or is not on the server PATH.')
            env = {**os.environ, 'OLLAMA_HOST': endpoint}
            with (_paths() / 'server.log').open('ab') as log:
                child = subprocess.Popen([binary, 'serve'], env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                         start_new_session=os.name != 'nt', creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
            _children[child.pid] = child
            identity = _identity(child.pid)
            if not identity:
                _children.pop(child.pid, None)
                child.terminate(); child.wait(timeout=3)
                raise RuntimeErrorDetail('Could not verify the new Ollama process. Check the local runtime log.')
            (_paths() / 'server.json').write_text(json.dumps({'pid': child.pid, 'identity': identity, 'endpoint': endpoint}))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if _online(endpoint): return server_status()
                if child.poll() is not None:
                    _children.pop(child.pid, None)
                    (_paths() / 'server.json').unlink(missing_ok=True)
                    raise RuntimeErrorDetail('Ollama could not start. Check .runtime/ollama/server.log.')
                time.sleep(.1)
            return server_status()
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeErrorDetail('The local server command failed. Check the runtime log or launch Ollama manually.') from error


def running_models():
    endpoint = local_endpoint()
    binary = shutil.which('ollama')
    if not binary:
        raise RuntimeErrorDetail('Ollama is not installed or is not on the server PATH.')
    if not _online(endpoint):
        return {'running': False, 'models': [], 'output': 'Ollama is off. Start the server to list loaded models.'}
    try:
        result = subprocess.run([binary, 'ps'], env={**os.environ, 'OLLAMA_HOST': endpoint}, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeErrorDetail('Could not run ollama ps. Refresh and try again.') from error
    if result.returncode:
        raise RuntimeErrorDetail('ollama ps failed. Refresh the server status and try again.')
    output = result.stdout[:32000]
    lines = [line for line in output.splitlines() if line.strip()]
    models = []
    if lines:
        headers = [column.lower() for column in re.split(r"\s{2,}", lines[0].strip())]
        for line in lines[1:101]:
            values = re.split(r"\s{2,}", line.strip())
            row = dict(zip(headers, values))
            if row.get('name'):
                models.append({key: row.get(key, '') for key in ('name', 'size', 'processor', 'context', 'until')})
    return {'running': True, 'models': models, 'output': output or 'No models are loaded.'}
