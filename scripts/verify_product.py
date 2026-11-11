"""Exercise the installed service and SDK using disposable identities and loopback HTTP."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import socket
import sys
import sysconfig
import tempfile
import threading
import time
import uuid

import aixand_filesystem
import carrier
import httpx
import uvicorn
from carrier.service import create_app


def exercise(state):
    site = Path(sysconfig.get_path("purelib")).resolve()
    for module in (carrier, aixand_filesystem):
        assert Path(module.__file__).resolve().is_relative_to(site), module.__name__
    assert callable(aixand_filesystem.lock_file)
    state.mkdir(parents=True, exist_ok=True)
    database = state / "carrier.db"
    identities = [state / "sender.json", state / "receiver.json"]
    for address, path in zip(("installer/sender", "installer/receiver"), identities):
        carrier.ensure_session(database=database, credentials=path, address=address)
        before = path.read_bytes()
        carrier.ensure_session(database=database, credentials=path, address=address)
        assert path.read_bytes() == before
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(create_app(database), log_level="error", lifespan="off")
        )
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [listener]}, daemon=True
        )
        thread.start()
        url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 15
            with httpx.Client(trust_env=False, timeout=1) as client:
                while time.monotonic() < deadline:
                    try:
                        if client.get(url + "/health").json() == {
                            "status": "ok",
                            "service": "carrier",
                        }:
                            break
                    except (httpx.HTTPError, ValueError):
                        pass
                    time.sleep(0.05)
                else:
                    raise RuntimeError("Installed Carrier did not become healthy")

            async def exchange():
                async with (
                    carrier.Client(url=url, credentials=identities[0]) as sender,
                    carrier.Client(url=url, credentials=identities[1]) as receiver,
                ):
                    key = uuid.uuid4().hex
                    sent = await sender.send(
                        "portable installation verified",
                        to="installer/receiver",
                        idempotency_key=key,
                    )
                    assert (
                        await sender.send(
                            "portable installation verified",
                            to="installer/receiver",
                            idempotency_key=key,
                        )
                    ).id == sent.id
                    message = next(
                        m
                        for m in (await receiver.receive_pending()).messages
                        if m.id == sent.id
                    )
                    await message.reply("received")
                    await message.ack()
                    answer = await sender.wait_for_reply(sent, timeout=3)
                    assert answer.content == "received"
                    await answer.ack()
                    assert (await sender.delivery_status(key))[
                        "status"
                    ] == "acknowledged"

            asyncio.run(exchange())
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("Temporary Carrier service did not stop")
    return {
        "verified": True,
        "installed_imports": True,
        "http_exchange": True,
        "credentials_reused": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="carrier-product-check-") as temporary:
        print(json.dumps(exercise(args.state_root or Path(temporary))))
