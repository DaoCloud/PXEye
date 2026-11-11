"""Durable, private stage journal shared by packaging and onsite entry points."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import signal
import tempfile
import time


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


class Progress:
    def __init__(self, directory, identity):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / 'progress.json'
        self.events = self.directory / 'events.jsonl'
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {
            'schema_version': 1, 'identity': identity, 'status': 'pending', 'stages': {}}
        if self.state['identity'] != identity:
            raise ValueError('Inputs or implementation changed; use a new version/work directory')
        self.save()

    def save(self):
        self.state['updated_at'] = datetime.now(timezone.utc).isoformat()
        atomic_json(self.path, self.state)

    @contextmanager
    def stage(self, key, title):
        started = time.monotonic()
        row = self.state['stages'].setdefault(key, {})
        attempt = row.get('attempt', 0) + 1
        row.update(status='running', attempt=attempt, title=title,
                   started_at=datetime.now(timezone.utc).isoformat())
        row.pop('error', None)
        self.state.pop('error', None)
        self.state.update(status='running', current_stage=key)
        self.save()
        print(f'STAGE [{key}] {title} (attempt {attempt})', flush=True)
        try:
            yield row
        except BaseException as error:
            row.update(status='failed', error=str(error) or type(error).__name__)
            self.state['status'] = 'failed'
            print(f'FAILED [{key}]; fix the cause and rerun the same command; progress: {self.path}', flush=True)
            raise
        else:
            row['status'] = 'completed'
            print(f'DONE [{key}]', flush=True)
        finally:
            row.update(seconds=round(time.monotonic() - started, 3),
                       ended_at=datetime.now(timezone.utc).isoformat())
            self.save()
            with self.events.open('a') as stream:
                os.chmod(self.events, 0o600)
                stream.write(json.dumps({'stage': key, **row}, ensure_ascii=False) + '\n')
                stream.flush(); os.fsync(stream.fileno())

    def fail(self, error):
        self.state.update(status='failed', error=str(error) or type(error).__name__)
        self.save()
        print('RUN_FAILED; progress:', self.path, flush=True)

    def complete(self):
        self.state.pop('error', None)
        self.state.update(status='completed', current_stage=None)
        self.save()


class Tee:
    def __init__(self, terminal, log):
        self.terminal, self.log = terminal, log

    def write(self, text):
        self.terminal.write(text); self.log.write(text)
        return len(text)

    def flush(self):
        self.terminal.flush(); self.log.flush()

    def isatty(self):
        return False


@contextmanager
def transcript(directory):
    path = Path(directory) / 'run.log'
    with path.open('a', buffering=1) as stream:
        path.chmod(0o600)
        stdout, stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = Tee(stdout, stream), Tee(stderr, stream)
        try:
            yield
        finally:
            sys.stdout, sys.stderr = stdout, stderr


def install_signal_handlers():
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Terminated')
    signal.signal(signal.SIGTERM, interrupted)
