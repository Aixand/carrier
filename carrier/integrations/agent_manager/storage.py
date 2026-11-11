"""Private adapter journals and process-safe operation leases."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
import json
import os
from pathlib import Path
import tempfile
from aixand_filesystem import lock_file, private_path


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            private_path(temporary)
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


@contextmanager
def lease(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a') as stream:
        private_path(path)
        lock_file(stream, blocking=True)
        yield


@asynccontextmanager
async def async_lease(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a') as stream:
        private_path(path)
        while True:
            try:
                lock_file(stream, blocking=False)
                break
            except BlockingIOError:
                await asyncio.sleep(.05)
        yield
