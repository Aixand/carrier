"""Local, recoverable mailbox provisioning for applications sharing a Carrier store."""
import hashlib
import json
import os
from pathlib import Path
import secrets

from .service import Store, Rename


def ensure_session(*, database, credentials, address, name=None):
    """Create one identity, or restore the same interrupted provisioning intent.

    Existing credentials are preserved and must name the requested address. This
    local administration API requires the database served by the HTTP service.
    A private pending file retains the token before the database commit so a
    process crash cannot strand an identity with an unrecoverable token.
    """
    from aixand_filesystem import lock_file, private_path, secure_file
    if not address or len(address) > 200 or any(c.isspace() for c in address):
        raise ValueError("Use a nonempty address without whitespace (maximum 200 characters)")
    name = Rename(name=name).name
    path = Path(credentials).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    pending = path.with_suffix(path.suffix + ".pending")
    with path.with_suffix(path.suffix + ".lock").open("a") as owner:
        private_path(owner.name)
        lock_file(owner, blocking=True)
        if path.exists():
            value = json.loads(path.read_text())
            if value.get("address") != address or not isinstance(value.get("token"), str) or not value["token"]:
                raise ValueError("Existing credentials do not match the requested identity")
            return path
        if pending.exists():
            value = json.loads(pending.read_text())
            if value.get("address") != address or not isinstance(value.get("token"), str) or not value["token"]:
                raise ValueError("Pending credentials do not match the requested identity")
        else:
            value = {"address": address, "token": secrets.token_urlsafe(32)}
            fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as stream:
                secure_file(stream)
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
        private_path(pending)
        store = Store(str(Path(database).expanduser().resolve()))
        token_hash = hashlib.sha256(value["token"].encode()).hexdigest()
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT token_hash FROM sessions WHERE address=?", (address,)).fetchone()
            if old and old["token_hash"] != token_hash:
                raise ValueError("Address already exists with different credentials; restore its original credential file")
            if not old:
                db.execute("INSERT INTO sessions(address,token_hash,name) VALUES (?,?,?)", (address, token_hash, name))
        pending.replace(path)
        if os.name == "posix":
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return path
