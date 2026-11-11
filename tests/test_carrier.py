from aixand_filesystem import verify_private

import asyncio
import json
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import AsyncExitStack

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from carrier.service import Store, create_app
from carrier.adapter import create_adapter


def test_service_does_not_expose_dashboard(tmp_path):
    with TestClient(create_app(str(tmp_path / 'carrier.db'))) as client:
        assert client.get('/health').json() == {'status': 'ok', 'service': 'carrier'}
        for path in ('/dashboard', '/dashboard/', '/dashboard/assets/dashboard.js',
                     '/dashboard/api/overview', '/dashboard/api/messages'):
            assert client.get(path).status_code == 404


def test_serve_rejects_removed_dashboard_flag(monkeypatch, capsys):
    from carrier.cli import main

    monkeypatch.setattr(sys, 'argv', ['carrier', 'serve', '--dashboard'])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert 'unrecognized arguments: --dashboard' in capsys.readouterr().err


def test_wait_timeout_validation_errors_and_cancellation(monkeypatch):
    from mcp.server.fastmcp.exceptions import ToolError

    original_client = httpx.AsyncClient

    async def exercise():
        requested = asyncio.Event()
        cancelled = asyncio.Event()
        mode = "empty"

        async def respond(request):
            requested.set()
            if mode == "slow":
                try:
                    await asyncio.sleep(60)
                finally:
                    cancelled.set()
            if mode == "unauthorized":
                return httpx.Response(401, json={"detail": "Invalid session credentials"})
            if mode == "unavailable":
                raise httpx.ConnectError("offline", request=request)
            if request.url.path == "/whoami":
                return httpx.Response(200, json={"address": "test", "name": None, "recipient": None})
            return httpx.Response(200, json={"messages": [], "next_after": None})

        transport = httpx.MockTransport(respond)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(**(kwargs | {"transport": transport})))
        adapter = create_adapter("http://carrier", "test-token")
        wait = adapter._tool_manager.get_tool("wait")
        for args in ({"timeout_seconds": value} for value in (0, -1, 301, float("inf"), float("nan"))):
            with pytest.raises(ToolError):
                await wait.run(args)
        for limit in (0, 101):
            with pytest.raises(ToolError):
                await wait.run({"limit": limit})
        assert not requested.is_set()

        started = time.monotonic()
        assert await wait.run({"timeout_seconds": 0.1}) == {
            "status": "timeout", "messages": [], "next_after": None}
        assert 0.08 <= time.monotonic() - started < 2
        for mode, message in (("unauthorized", "Invalid session credentials"), ("unavailable", "service is unavailable")):
            with pytest.raises(ToolError, match=message):
                await wait.run({"timeout_seconds": 1})

        # The overall deadline also bounds an in-flight HTTP request.
        mode = "slow"
        assert (await wait.run({"timeout_seconds": 0.1}))["status"] == "timeout"
        assert cancelled.is_set()
        cancelled.clear()
        requested.clear()
        task = asyncio.create_task(wait.run({"timeout_seconds": 45}))
        await asyncio.wait_for(requested.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()

    asyncio.run(exercise())


def test_wait_inbox_isolation_and_pagination(tmp_path, monkeypatch):
    path = str(tmp_path / "carrier.db")
    store = Store(path)
    tokens = {address: store.provision(address) for address in ("a", "b", "c")}
    app = create_app(path)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {tokens['a']}"}
        client.post("/connect", headers=headers, json={"to": "b"})
        for content in ("one", "two"):
            client.post("/send", headers=headers, json={"content": content})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        **(kwargs | {"transport": httpx.ASGITransport(app=app)})))

    async def exercise():
        b = create_adapter("http://carrier", tokens["b"])
        c = create_adapter("http://carrier", tokens["c"])
        page = await b._tool_manager.get_tool("wait").run({"limit": 1})
        assert page["status"] == "messages"
        assert [m["content"] for m in page["messages"]] == ["one"]
        assert page["next_after"] == page["messages"][0]["id"]
        remaining = await b._tool_manager.get_tool("receive_pending").run({"after": page["next_after"]})
        assert [m["content"] for m in remaining["messages"]] == ["two"]
        assert (await c._tool_manager.get_tool("wait").run({"timeout_seconds": 0.1}))["status"] == "timeout"

    asyncio.run(exercise())


def test_wait_stops_when_conversation_binding_closes(tmp_path, monkeypatch):
    from mcp.server.fastmcp.exceptions import ToolError
    binding = tmp_path / "binding.json"
    binding.write_text(json.dumps({"status": "bound"}))
    original_client = httpx.AsyncClient
    polls = []

    def respond(request):
        if request.url.path == "/whoami":
            return httpx.Response(200, json={"address": "a"})
        polls.append(request)
        binding.write_text(json.dumps({"status": "closed"}))
        return httpx.Response(200, json={"messages": [], "next_after": None})

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(**(kwargs | {"transport": transport})))

    async def exercise():
        adapter = create_adapter("http://carrier", "token", str(binding))
        with pytest.raises(ToolError, match="not bound"):
            await asyncio.wait_for(adapter._tool_manager.get_tool("wait").run({"timeout_seconds": 45}), timeout=2)
        assert len(polls) == 1

    asyncio.run(exercise())


def test_routing_authentication_and_persistence(tmp_path):
    path = str(tmp_path / "carrier.db")
    store = Store(path)
    headers = {name: {"Authorization": f"Bearer {store.provision(name)}"}
               for name in ("a/1", "b/1", "b/2")}
    with TestClient(create_app(path)) as client:
        assert client.get("/whoami").status_code == 401
        assert client.get("/whoami", headers={"Authorization": "Bearer invalid"}).status_code == 401
        assert client.post("/send", headers=headers["a/1"], json={"content": "hi"}).status_code == 409
        assert client.post("/connect", headers=headers["a/1"], json={"to": "missing"}).status_code == 404
        assert client.post("/connect", headers=headers["a/1"], json={"to": "b/1"}).status_code == 200
        for content in ("hello", "review this"):
            assert client.post("/send", headers=headers["a/1"], json={"content": content}).status_code == 200
        assert client.get("/whoami", headers=headers["b/1"]).json()["recipient"] is None
        assert client.get("/receive", headers=headers["b/2"]).json()["messages"] == []
        page = client.get("/receive?limit=1", headers=headers["b/1"]).json()
        assert page["messages"][0]["content"] == "hello"
        page = client.get(f"/receive?after={page['next_after']}", headers=headers["b/1"]).json()
        assert [m["content"] for m in page["messages"]] == ["review this"]
        assert client.post("/send", headers=headers["a/1"], json={"content": ""}).status_code == 422
        assert client.get("/receive?limit=101", headers=headers["b/1"]).status_code == 422
    with TestClient(create_app(path)) as restarted:
        assert restarted.get("/whoami", headers=headers["a/1"]).json()["recipient"] == "b/1"
        assert len(restarted.get("/receive", headers=headers["b/1"]).json()["messages"]) == 2


def test_real_mcp_roundtrip_and_restart(tmp_path):
    path = str(tmp_path / "carrier.db")
    for address in ("a", "b"):
        result = subprocess.run(
            [sys.executable, "-m", "carrier.cli", "session", address, "--db", path,
             "--credentials", str(tmp_path / f"{address}.json"), "--name", f"agent-{address}"], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        verify_private(tmp_path / f"{address}.json")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"

    async def exchange(resumed=False):
        binding = tmp_path / 'binding.json'
        binding.write_text(json.dumps({'status': 'pending'}))
        async with AsyncExitStack() as stack:
            sessions = {}
            for address in ("a", "b"):
                streams = await stack.enter_async_context(stdio_client(StdioServerParameters(
                    command=sys.executable, args=["-m", "carrier.cli", "mcp", "--url", url,
                    "--credentials", str(tmp_path / f"{address}.json")]
                    + (["--binding", str(binding)] if address == 'a' else []))))
                session = await stack.enter_async_context(ClientSession(*streams))
                await session.initialize()
                sessions[address] = session

            blocked = await sessions['a'].call_tool('whoami', {})
            assert blocked.isError
            assert (await sessions['a'].call_tool('wait', {"timeout_seconds": 1})).isError
            binding.write_text(json.dumps({'status': 'bound'}))

            async def call(address, tool, arguments=None):
                result = await sessions[address].call_tool(tool, arguments or {})
                assert not result.isError, result
                return json.loads(result.content[0].text)

            tools = await sessions["a"].list_tools()
            assert {t.name for t in tools.tools} == {"whoami", "connect", "send", "receive", "list_sessions", "rename",
                                                   "ack", "delivery_status", "receive_pending", "wait"}
            directory = await call("a", "list_sessions", {"limit": 1})
            assert directory["sessions"] == [{"address": "a", "name": "agent-a"}]
            assert (await call("a", "list_sessions", {"after": directory["next_after"]}))["sessions"][0]["address"] == "b"
            if resumed:
                assert (await call("b", "receive_pending"))["messages"] == []
                assert (await call("b", "wait", {"timeout_seconds": 0.1}))["status"] == "timeout"
                assert (await call("a", "delivery_status", {"message_id": "review-001"}))["status"] == "acknowledged"
                await call("a", "send", {"content": "Review this?", "message_id": "review-001"})
                assert (await call("b", "receive_pending"))["messages"] == []
                assert (await call("a", "whoami"))["recipient"] == "b"
                assert (await call("b", "whoami"))["name"] == "reviewer-renamed"
                assert (await call("a", "receive"))["messages"][0]["content"] == "Sure!"
                await call("a", "send", {"content": "After restart"})
                assert len((await call("b", "receive"))["messages"]) == 2
            else:
                error = await sessions["a"].call_tool("send", {"content": "too early"})
                assert error.isError
                await call("b", "rename", {"name": "reviewer"})
                assert (await call("a", "connect", {"to": "reviewer"}))["recipient"] == "b"
                await call("b", "rename", {"name": "reviewer-renamed"})
                waiting = asyncio.create_task(call("b", "wait", {"timeout_seconds": 5}))
                await asyncio.sleep(0.2)
                assert not waiting.done()
                original = await call("a", "send", {"content": "Review this?", "message_id": "review-001"})
                arrived = await asyncio.wait_for(waiting, timeout=5)
                assert arrived["status"] == "messages"
                assert arrived["messages"] == [original]
                assert (await call("b", "wait", {"timeout_seconds": 1})) == arrived
                assert (await call("a", "send", {"content": "Review this?", "message_id": "review-001"}))["id"] == original["id"]
                assert (await call("a", "delivery_status", {"message_id": "review-001"}))["status"] == "stored"
                pending = await call("b", "receive_pending")
                assert len(pending["messages"]) == 1
                await call("b", "ack", {"message_id": pending["messages"][0]["id"]})
                assert await call("b", "wait", {"timeout_seconds": 0.1}) == {
                    "status": "timeout", "messages": [], "next_after": None}
                assert (await call("b", "receive"))["messages"][0]["sender"] == "a"
                await call("b", "connect", {"to": "a"})
                answer = await call("b", "send", {"content": "Sure!", "to": "a",
                                    "reply_to": original["id"], "message_id": "answer-001"})
                replies = await call("a", "wait", {"reply_to": original["id"], "timeout_seconds": 1})
                assert replies["messages"] == [answer]
                assert answer["reply_to"] == original["id"]

    for resumed in (False, True):
        process = subprocess.Popen([sys.executable, "-m", "carrier.cli", "serve", "--db", path,
                                    "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with httpx.Client(trust_env=False) as client:
                for _ in range(100):
                    assert process.poll() is None, "Carrier service exited unexpectedly"
                    try:
                        if client.get(url + "/health").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(0.05)
                else:
                    raise AssertionError("Carrier did not start")
            asyncio.run(exchange(resumed))
            status = subprocess.run([sys.executable, '-m', 'carrier.cli', 'status', '--url', url, '--json'],
                                    capture_output=True, text=True)
            assert status.returncode == 0, status.stderr
            assert json.loads(status.stdout) == {'status': 'running', 'url': url}
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def test_status_rejects_other_services_and_connection_errors(monkeypatch, capsys):
    from carrier.cli import main
    import pytest
    original_client = httpx.Client
    monkeypatch.setattr(sys, 'argv', ['carrier', 'status', '--json'])
    for payload in ({'status': 'ok'}, {'service': 'carrier', 'status': 'failed'}):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original_client(transport=transport, **kwargs))
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 1
        assert json.loads(capsys.readouterr().out)['status'] == 'unavailable'
    def disconnected(request):
        raise httpx.ConnectError('connection refused')
    transport = httpx.MockTransport(disconnected)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'unavailable'


def test_directory_names_and_stable_destinations(tmp_path):
    path = str(tmp_path / "carrier.db")
    store = Store(path)
    headers = {address: {"Authorization": f"Bearer {store.provision(address)}"} for address in ("a", "b", "c")}
    with TestClient(create_app(path)) as client:
        assert client.get("/sessions").status_code == 401
        assert client.post("/rename", json={"name": "stolen"}).status_code == 401
        for bad in ("", " ", " reviewer", "reviewer ", "line\nbreak", "x" * 81):
            assert client.post("/rename", headers=headers["b"], json={"name": bad}).status_code == 422
        for address in ("b", "c"):
            assert client.post("/rename", headers=headers[address], json={"name": "reviewer"}).status_code == 200
        assert client.post("/connect", headers=headers["a"], json={"to": "b"}).status_code == 200
        assert client.post("/connect", headers=headers["a"], json={"to": "reviewer"}).status_code == 409
        assert client.get("/whoami", headers=headers["a"]).json()["recipient"] == "b"
        assert client.post("/connect", headers=headers["a"], json={"to": "Reviewer"}).status_code == 404
        client.post("/rename", headers=headers["c"], json={"name": None})
        assert client.post("/connect", headers=headers["a"], json={"to": "reviewer"}).json()["recipient"] == "b"
        client.post("/rename", headers=headers["b"], json={"name": "builder"})
        client.post("/rename", headers=headers["c"], json={"name": "reviewer"})
        assert client.post("/send", headers=headers["a"], json={"content": "still b"}).json()["recipient"] == "b"
        assert client.get("/receive", headers=headers["c"]).json()["messages"] == []
        # A display name cannot hijack another session's permanent address.
        client.post("/rename", headers=headers["c"], json={"name": "b"})
        assert client.post("/connect", headers=headers["a"], json={"to": "b"}).json()["recipient"] == "b"
        page = client.get("/sessions?limit=2", headers=headers["a"]).json()
        assert page == {"sessions": [{"address": "a", "name": None}, {"address": "b", "name": "builder"}], "next_after": "b"}
        assert client.get("/sessions?after=b&limit=2", headers=headers["a"]).json() == {
            "sessions": [{"address": "c", "name": "b"}], "next_after": None}
        assert client.get("/sessions?after=z", headers=headers["a"]).json() == {"sessions": [], "next_after": None}
        for limit in (0, 101):
            assert client.get(f"/sessions?limit={limit}", headers=headers["a"]).status_code == 422
        assert client.get("/whoami", headers=headers["a"]).json()["name"] is None


def test_migrates_legacy_database_without_changing_identity(tmp_path):
    import hashlib
    path = str(tmp_path / "legacy.db")
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE sessions (address TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
                                   recipient TEXT REFERENCES sessions(address));
            CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL REFERENCES sessions(address), recipient TEXT NOT NULL REFERENCES sessions(address),
                content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT 'legacy');
        """)
        db.execute("INSERT INTO sessions VALUES (?, ?, ?)", ("b", hashlib.sha256(b"b-token").hexdigest(), None))
        db.execute("INSERT INTO sessions VALUES (?, ?, ?)", ("a", hashlib.sha256(b"a-token").hexdigest(), "b"))
        db.execute("INSERT INTO messages(sender, recipient, content) VALUES ('a', 'b', 'saved')")
    for _ in range(2):
        with TestClient(create_app(path)) as client:
            assert client.get("/whoami", headers={"Authorization": "Bearer a-token"}).json() == {
                "address": "a", "name": None, "recipient": "b"}
            assert client.get("/receive", headers={"Authorization": "Bearer b-token"}).json()["messages"][0]["content"] == "saved"
            pending = client.get("/receive_pending", headers={"Authorization": "Bearer b-token"}).json()["messages"]
            assert len(pending) == 1 and pending[0]["message_id"] is None and pending[0]["acknowledged_at"] is None


def test_reliable_delivery_isolation_pagination_and_restart(tmp_path):
    path = str(tmp_path / "carrier.db")
    store = Store(path)
    headers = {address: {"Authorization": f"Bearer {store.provision(address)}"} for address in ("a", "b", "c")}
    with TestClient(create_app(path)) as client:
        client.post("/connect", headers=headers["a"], json={"to": "b"})
        def send(content, key=None, sender="a"):
            return client.post("/send", headers=headers[sender], json={"content": content, "message_id": key})
        first = send("one", "key").json()
        second = send("two", "key-2").json()
        assert send("changed", "key").status_code == 409
        assert send("invalid", "").status_code == 422
        assert send("invalid", "x" * 201).status_code == 422
        client.post("/connect", headers=headers["a"], json={"to": "c"})
        assert send("one", "key").json() == first
        assert client.get("/receive_pending", headers=headers["c"]).json()["messages"] == []
        client.post("/connect", headers=headers["c"], json={"to": "b"})
        third = send("other sender", "key", "c").json()
        assert third["id"] != first["id"]
        for address in ("a", "c"):
            assert client.post("/ack", headers=headers[address], json={"message_id": first["id"]}).status_code == 404
        assert client.get("/delivery_status?message_id=key-2", headers=headers["c"]).status_code == 404
        assert client.get("/delivery_status?message_id=key", headers=headers["b"]).status_code == 404
        assert client.get("/receive_pending").status_code == 401
        assert client.get("/delivery_status?message_id=key").status_code == 401
        assert client.post("/ack", json={"message_id": first["id"]}).status_code == 401
        assert client.post("/ack", headers=headers["b"], json={"message_id": 0}).status_code == 422
        assert client.post("/ack", headers=headers["b"], json={"message_id": 99999}).status_code == 404
        for query in ("limit=0", "limit=101", "after=-1"):
            assert client.get("/receive_pending?" + query, headers=headers["b"]).status_code == 422
        page = client.get("/receive_pending?limit=1", headers=headers["b"]).json()
        assert page["messages"] == [first] and page["next_after"] == first["id"]
        assert client.get("/delivery_status?message_id=key", headers=headers["a"]).json()["status"] == "stored"
        acknowledgement = client.post("/ack", headers=headers["b"], json={"message_id": second["id"]}).json()
        assert acknowledgement["status"] == "acknowledged" and acknowledgement["acknowledged_at"]
        assert client.post("/ack", headers=headers["b"], json={"message_id": second["id"]}).json() == acknowledgement
        page = client.get(f"/receive_pending?after={page['next_after']}&limit=1", headers=headers["b"]).json()
        assert page["messages"] == [third] and page["next_after"] is None
        assert len(client.get("/receive", headers=headers["b"]).json()["messages"]) == 3
        # Legacy unkeyed sends remain separate and acknowledgeable.
        assert send("legacy").json()["id"] != send("legacy").json()["id"]
    with TestClient(create_app(path)) as client:
        pending = client.get("/receive_pending", headers=headers["b"]).json()["messages"]
        assert [m["id"] for m in pending] == [first["id"], third["id"]]
        assert client.get("/delivery_status?message_id=key-2", headers=headers["a"]).json()["acknowledged_at"] == acknowledgement["acknowledged_at"]
        retry = client.post("/send", headers=headers["a"], json={"content": "two", "message_id": "key-2"}).json()
        assert retry["id"] == second["id"] and retry["acknowledged_at"] == acknowledgement["acknowledged_at"]


def test_concurrent_retries_store_one_message(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path = str(tmp_path / "carrier.db")
    store = Store(path)
    token = store.provision("a")
    store.provision("b")
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(path)) as client:
        client.post("/connect", headers=headers, json={"to": "b"})
        def send(_):
            response = client.post("/send", headers=headers, json={"content": "same", "message_id": "retry"})
            assert response.status_code == 200
            return response.json()["id"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert len(set(pool.map(send, range(16)))) == 1
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
