import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from . import __version__


class Connect(BaseModel):
    to: str = Field(min_length=1, max_length=200)


class Send(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)
    message_id: str | None = Field(default=None, min_length=1, max_length=200)
    to: str | None = Field(default=None, min_length=1, max_length=200)
    reply_to: int | None = Field(default=None, gt=0, strict=True)


class Ack(BaseModel):
    message_id: int = Field(gt=0)


class Rename(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if value is not None and (value != value.strip() or not value.isprintable()):
            raise ValueError("Names must be printable, with no leading or trailing whitespace")
        return value


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    address TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
                    recipient TEXT REFERENCES sessions(address)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT NOT NULL REFERENCES sessions(address),
                    recipient TEXT NOT NULL REFERENCES sessions(address),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE INDEX IF NOT EXISTS inbox ON messages(recipient, id);
            """)
            # Serialize the migration with other service/provisioning processes.
            db.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(sessions)")}
            if "name" not in columns:
                db.execute("ALTER TABLE sessions ADD COLUMN name TEXT")
            db.execute("CREATE INDEX IF NOT EXISTS session_names ON sessions(name)")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(messages)")}
            if "message_id" not in columns:
                db.execute("ALTER TABLE messages ADD COLUMN message_id TEXT")
            if "acknowledged_at" not in columns:
                db.execute("ALTER TABLE messages ADD COLUMN acknowledged_at TEXT")
            if "reply_to" not in columns:
                db.execute("ALTER TABLE messages ADD COLUMN reply_to INTEGER REFERENCES messages(id)")
            if "requested_to" not in columns:
                db.execute("ALTER TABLE messages ADD COLUMN requested_to TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS sender_message_ids ON messages(sender, message_id)")
            db.execute("CREATE INDEX IF NOT EXISTS pending_inbox ON messages(recipient, id) WHERE acknowledged_at IS NULL")
            db.execute("CREATE INDEX IF NOT EXISTS inbox_replies ON messages(recipient, reply_to, id)")
            db.execute("""CREATE TABLE IF NOT EXISTS budget_sources (
                address TEXT PRIMARY KEY REFERENCES sessions(address),
                recipient TEXT NOT NULL REFERENCES sessions(address))""")
            db.execute("""CREATE TABLE IF NOT EXISTS budget_events (
                source TEXT NOT NULL REFERENCES budget_sources(address),
                event_id TEXT NOT NULL, payload TEXT NOT NULL,
                message_id INTEGER NOT NULL REFERENCES messages(id),
                PRIMARY KEY(source, event_id))""")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def provision(self, address: str, name: str | None = None) -> str:
        if not address or len(address) > 200 or any(c.isspace() for c in address):
            raise ValueError("Use a nonempty address without whitespace (maximum 200 characters).")
        token = secrets.token_urlsafe(32)
        name = Rename(name=name).name
        with self.db() as db:
            db.execute("INSERT INTO sessions(address, token_hash, name) VALUES (?, ?, ?)",
                       (address, hashlib.sha256(token.encode()).hexdigest(), name))
        return token


    def provision_budget(self, address: str, recipient: str) -> str:
        if not address or len(address) > 200 or any(c.isspace() for c in address):
            raise ValueError("Use a nonempty source address without whitespace (maximum 200 characters).")
        token = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM sessions WHERE address = ?', (recipient,)).fetchone():
                raise ValueError('Budget recipient must be an existing exact session address')
            db.execute('INSERT INTO sessions(address, token_hash, recipient, name) VALUES (?, ?, ?, ?)',
                       (address, hashlib.sha256(token.encode()).hexdigest(), recipient, 'Budget monitor'))
            db.execute('INSERT INTO budget_sources(address, recipient) VALUES (?, ?)', (address, recipient))
        return token


def create_app(path: str) -> FastAPI:
    store = Store(path)
    app = FastAPI(title="Carrier", version=__version__)
    bearer = HTTPBearer(auto_error=False)

    def identity(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        token = credentials.credentials if credentials else ""
        with store.db() as db:
            row = db.execute("SELECT * FROM sessions WHERE token_hash = ?",
                             (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if row is None:
            raise HTTPException(401, "Invalid session credentials")
        return dict(row)

    def resolve(db, destination):
        # A retry is resolved from its stored request before this is called.
        row = db.execute("SELECT address FROM sessions WHERE address = ?", (destination,)).fetchone()
        if row is None:
            matches = db.execute("SELECT address FROM sessions WHERE name = ? LIMIT 2", (destination,)).fetchall()
            if not matches:
                raise HTTPException(404, "Recipient session does not exist")
            if len(matches) > 1:
                raise HTTPException(409, "Ambiguous recipient name; use list_sessions() and an exact address")
            row = matches[0]
        return row["address"]

    def message(row):
        result = dict(row)
        result.pop("requested_to", None)
        return result

    @app.get("/capabilities")
    def capabilities(session=Depends(identity)):
        return {"protocol_version": 1, "features": ["addressed_send", "reply_to"]}

    @app.get("/health")
    def health():
        with store.db() as db:
            db.execute('SELECT 1 FROM sessions LIMIT 1').fetchone()
        return {"status": "ok", "service": "carrier"}

    @app.get("/whoami")
    def whoami(session=Depends(identity)):
        return {"address": session["address"], "name": session["name"], "recipient": session["recipient"]}

    @app.get("/sessions")
    def list_sessions(after: str = "", limit: int = 50, session=Depends(identity)):
        if len(after) > 200 or not 1 <= limit <= 100:
            raise HTTPException(422, "after must be an address of at most 200 characters; limit must be between 1 and 100")
        with store.db() as db:
            rows = db.execute("SELECT address, name FROM sessions WHERE address > ? ORDER BY address LIMIT ?",
                              (after, limit + 1)).fetchall()
        sessions = [dict(row) for row in rows[:limit]]
        return {"sessions": sessions, "next_after": sessions[-1]["address"] if len(rows) > limit else None}

    @app.post("/rename")
    def rename(body: Rename, session=Depends(identity)):
        with store.db() as db:
            db.execute("UPDATE sessions SET name = ? WHERE address = ?", (body.name, session["address"]))
        return {"address": session["address"], "name": body.name}

    @app.post("/connect")
    def connect(body: Connect, session=Depends(identity)):
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            recipient = resolve(db, body.to)
            db.execute("UPDATE sessions SET recipient = ? WHERE address = ?",
                       (recipient, session["address"]))
        return {"address": session["address"], "recipient": recipient}

    @app.post("/send")
    def send(body: Send, session=Depends(identity)):
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if body.message_id is not None:
                original = db.execute("SELECT * FROM messages WHERE sender = ? AND message_id = ?",
                                      (session["address"], body.message_id)).fetchone()
                if original is not None:
                    same_route = ((body.to is None and original["requested_to"] is None)
                                  or (body.to is not None and original["requested_to"] is not None
                                      and body.to in (original["requested_to"], original["recipient"])))
                    if original["content"] != body.content or original["reply_to"] != body.reply_to or not same_route:
                        raise HTTPException(409, "message_id already used with different content, destination, or reply_to; use a new ID for a new message")
                    return message(original)
            recipient = (resolve(db, body.to) if body.to is not None else
                         db.execute("SELECT recipient FROM sessions WHERE address = ?",
                                    (session["address"],)).fetchone()[0])
            if recipient is None:
                raise HTTPException(409, "Select a recipient with connect(to=...) before sending")
            if body.reply_to is not None:
                parent = db.execute("SELECT sender FROM messages WHERE id = ? AND recipient = ?",
                                    (body.reply_to, session["address"])).fetchone()
                if parent is None:
                    raise HTTPException(404, "Reply parent not found in your inbox")
                if parent["sender"] != recipient:
                    raise HTTPException(409, "A reply must be addressed to the original sender")
            cursor = db.execute("""INSERT INTO messages(sender, recipient, content, message_id, requested_to, reply_to)
                                   VALUES (?, ?, ?, ?, ?, ?)""",
                                (session["address"], recipient, body.content, body.message_id, body.to, body.reply_to))
            return message(db.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)).fetchone())

    @app.post("/ack")
    def ack(body: Ack, session=Depends(identity)):
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM messages WHERE id = ? AND recipient = ?",
                             (body.message_id, session["address"])).fetchone()
            if row is None:
                raise HTTPException(404, "Message not found in your inbox")
            db.execute("""UPDATE messages SET acknowledged_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
                          WHERE id = ? AND acknowledged_at IS NULL""", (body.message_id,))
            row = db.execute("SELECT id, message_id, acknowledged_at FROM messages WHERE id = ?",
                             (body.message_id,)).fetchone()
            return {**dict(row), "status": "acknowledged"}

    @app.get("/delivery_status")
    def delivery_status(message_id: str, session=Depends(identity)):
        if not 1 <= len(message_id) <= 200:
            raise HTTPException(422, "message_id must be between 1 and 200 characters")
        with store.db() as db:
            row = db.execute("""SELECT id, message_id, recipient, created_at, acknowledged_at
                                FROM messages WHERE sender = ? AND message_id = ?""",
                             (session["address"], message_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Message not found among your keyed sends")
        return {**dict(row), "status": "acknowledged" if row["acknowledged_at"] else "stored"}

    @app.get("/receive_pending")
    def receive_pending(after: int = 0, limit: int = 50, reply_to: int | None = None, session=Depends(identity)):
        if after < 0 or not 1 <= limit <= 100 or (reply_to is not None and reply_to <= 0):
            raise HTTPException(422, "after must be nonnegative; limit must be between 1 and 100; reply_to must be positive")
        with store.db() as db:
            clause, values = ("", []) if reply_to is None else (" AND reply_to = ?", [reply_to])
            rows = db.execute("""SELECT * FROM messages WHERE recipient = ? AND id > ?
                                 AND acknowledged_at IS NULL""" + clause + " ORDER BY id LIMIT ?",
                              (session["address"], after, *values, limit + 1)).fetchall()
        messages = [message(row) for row in rows[:limit]]
        return {"messages": messages, "next_after": messages[-1]["id"] if len(rows) > limit else None}

    @app.get("/receive")
    def receive(after: int = 0, limit: int = 50, reply_to: int | None = None, session=Depends(identity)):
        if after < 0 or not 1 <= limit <= 100 or (reply_to is not None and reply_to <= 0):
            raise HTTPException(422, "after must be nonnegative; limit must be between 1 and 100; reply_to must be positive")
        with store.db() as db:
            clause, values = ("", []) if reply_to is None else (" AND reply_to = ?", [reply_to])
            rows = db.execute("SELECT * FROM messages WHERE recipient = ? AND id > ?" + clause + " ORDER BY id LIMIT ?",
                              (session["address"], after, *values, limit)).fetchall()
        messages = [message(row) for row in rows]
        return {"messages": messages, "next_after": messages[-1]["id"] if messages else after}

    @app.get("/sent")
    def sent(after: int = 0, limit: int = 50, reply_to: int | None = None, session=Depends(identity)):
        """Retained outgoing history for the authenticated sender only."""
        if after < 0 or not 1 <= limit <= 100 or (reply_to is not None and reply_to <= 0):
            raise HTTPException(422, "after must be nonnegative; limit must be between 1 and 100; reply_to must be positive")
        with store.db() as db:
            clause, values = ("", []) if reply_to is None else (" AND reply_to = ?", [reply_to])
            rows = db.execute("SELECT * FROM messages WHERE sender = ? AND id > ?" + clause + " ORDER BY id LIMIT ?",
                              (session["address"], after, *values, limit)).fetchall()
        messages = [message(row) for row in rows]
        return {"messages": messages, "next_after": messages[-1]["id"] if messages else after}

    from carrier.budget import register
    register(app, store, identity)

    return app
