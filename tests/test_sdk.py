import asyncio
import json

import httpx
import pytest

import carrier
from carrier.service import Store, create_app


@pytest.fixture
def mailboxes(tmp_path):
    path = str(tmp_path / "carrier.db")
    store = Store(path)
    tokens = {address: store.provision(address) for address in ("a", "b", "c")}
    app = create_app(path)

    def client(address):
        return carrier.Client(url="http://carrier", token=tokens[address], transport=httpx.ASGITransport(app=app))

    return client, path, tokens


def test_concurrent_addressed_sends_do_not_change_default(mailboxes):
    make, _, _ = mailboxes

    async def exercise():
        async with make("a") as a, make("b") as b, make("c") as c:
            await a.connect("c")
            sent = await asyncio.gather(*(a.send(str(i), to="b" if i % 2 else "c",
                                                idempotency_key=f"request-{i}") for i in range(24)))
            assert all(m.recipient == ("b" if i % 2 else "c") for i, m in enumerate(sent))
            assert (await a.whoami())["recipient"] == "c"
            assert len((await b.receive()).messages) == 12
            assert len((await c.receive()).messages) == 12
            same = await asyncio.gather(*(a.send("one", to="b", idempotency_key="same") for _ in range(12)))
            assert len({m.id for m in same}) == 1

    asyncio.run(exercise())


def test_retry_pins_resolved_address_across_rename_and_restart(mailboxes):
    make, path, tokens = mailboxes

    async def exercise():
        async with make("a") as a, make("b") as b, make("c") as c:
            await b.rename("brain")
            sent = await a.send("question", to="brain", idempotency_key="key")
            await b.rename(None)
            await c.rename("brain")
        async with carrier.Client(url="http://carrier", token=tokens["a"],
                                  transport=httpx.ASGITransport(app=create_app(path))) as a:
            assert (await a.send("question", to="brain", idempotency_key="key")).id == sent.id
            assert (await a.send("question", to="b", idempotency_key="key")).id == sent.id
            for change in ({"to": "c"}, {"to": None}, {"content": "changed"}, {"reply_to": 1}):
                values = dict(content="question", to="brain", idempotency_key="key") | change
                with pytest.raises(carrier.ConflictError):
                    await a.send(**values)

    asyncio.run(exercise())


def test_reply_correlation_authorization_and_pending_filter(mailboxes):
    make, _, _ = mailboxes

    async def exercise():
        async with make("a") as a, make("b") as b, make("c") as c:
            question = await a.send_json({"query": "transaction?"}, to="b", idempotency_key="q")
            received = (await b.wait(timeout=1)).messages[0]
            assert received.json() == {"query": "transaction?"}
            answer = await received.reply_json({"answer": "yes"}, idempotency_key="answer")
            assert answer.reply_to == question.id
            assert (await a.delivery_status("q"))["status"] == "stored"
            await received.ack()
            assert (await a.delivery_status("q"))["status"] == "acknowledged"
            await c.send("unrelated", to="a")
            matched = await a.wait_for_reply(question, timeout=1)
            assert matched.json() == {"answer": "yes"}
            await matched.ack()
            with pytest.raises(TimeoutError):
                await a.wait_for_reply(question, timeout=0.03, poll_interval=0.01)
            assert [m.content for m in (await a.receive_pending()).messages] == ["unrelated"]
            assert (await a.receive(reply_to=question.id)).messages[0].id == answer.id
            with pytest.raises(carrier.HTTPError) as error:
                await c.send("forged", to="a", reply_to=question.id)
            assert error.value.status_code == 404
            with pytest.raises(carrier.ConflictError):
                await b.send("misdirected", to="c", reply_to=question.id)
            with pytest.raises(ValueError):
                await question.reply("not an incoming message")
            with pytest.raises(ValueError):
                await b.wait_for_reply(question)

    asyncio.run(exercise())


def test_pending_pagination_restarts_from_oldest_unacked(mailboxes):
    make, _, _ = mailboxes

    async def exercise():
        async with make("a") as a, make("b") as b:
            sent = [await a.send(str(i), to="b") for i in range(4)]
            page = await b.receive_pending(limit=2)
            await page.messages[1].ack()
            tail = await b.receive_pending(after=page.next_after, limit=2)
            assert [m.id for m in tail.messages] == [m.id for m in sent[2:]]
            assert tail.next_after is None
            assert (await b.wait(limit=1)).messages[0].id == sent[0].id

    asyncio.run(exercise())


def test_consumer_is_sequential_replies_and_cancels_without_acknowledging_current(mailboxes):
    make, _, _ = mailboxes

    async def exercise():
        async with make("a") as a, make("b") as b:
            first = await a.send("first", to="b")
            second = await a.send("second", to="b")
            seen = []
            processing_second = asyncio.Event()

            @b.consumer()
            async def handle(message):
                seen.append(message.content)
                if message.content == "second":
                    processing_second.set()
                    await asyncio.Event().wait()
                await message.reply("processed", idempotency_key=f"reply-{message.id}")
                await message.ack()

            task = asyncio.create_task(b.run(poll_interval=0.01))
            await asyncio.wait_for(processing_second.wait(), 2)
            with pytest.raises(carrier.CarrierError, match="active consumer"):
                await b.run()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert seen == ["first", "second"]
            assert (await a.wait_for_reply(first, timeout=1)).content == "processed"
            assert [m.id for m in (await b.receive_pending()).messages] == [second.id]

    asyncio.run(exercise())


@pytest.mark.parametrize("ack_first", [False, True])
def test_handler_failure_stops_runner_and_preserves_ack_boundary(mailboxes, ack_first):
    make, _, _ = mailboxes

    async def exercise():
        async with make("a") as a, make("b") as b:
            await a.send("work", to="b")
            calls = 0

            async def handle(message):
                nonlocal calls
                calls += 1
                if ack_first:
                    await message.ack()
                raise RuntimeError("application failed")

            with pytest.raises(RuntimeError, match="application failed"):
                await b.consume(handle)
            assert calls == 1
            assert len((await b.receive_pending()).messages) == (0 if ack_first else 1)

    asyncio.run(exercise())


def test_consumer_requires_explicit_ack_and_can_restart(mailboxes):
    make, _, _ = mailboxes

    async def exercise():
        async with make("a") as a, make("b") as b:
            sent = await a.send("work", to="b")

            async def forget(message):
                await message.reply("answer", idempotency_key=f"reply-{message.id}")

            for _ in range(2):
                with pytest.raises(carrier.UnacknowledgedMessage) as error:
                    await b.consume(forget)
                assert error.value.message_id == sent.id
            assert len((await a.receive()).messages) == 1
            assert len((await b.receive_pending()).messages) == 1

    asyncio.run(exercise())


def test_wait_wakes_without_blocking_event_loop_and_idle_cancel(mailboxes):
    make, _, _ = mailboxes

    async def exercise():
        async with make("a") as a, make("b") as b:
            task = asyncio.create_task(b.wait(timeout=2, poll_interval=0.01))
            await asyncio.sleep(0.02)
            assert not task.done()
            await a.send("wake", to="b")
            message = (await task).messages[0]
            await message.ack()
            task = asyncio.create_task(b.wait(timeout=60, poll_interval=0.01))
            await asyncio.sleep(0.02)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert (await b.wait(timeout=0.02)).status == "timeout"

    asyncio.run(exercise())


def test_old_service_cannot_silently_misroute_explicit_send():
    writes = []

    def respond(request):
        if request.url.path == "/whoami":
            return httpx.Response(200, json={"address": "a"})
        if request.url.path == "/capabilities":
            return httpx.Response(404, json={"detail": "Not Found"})
        writes.append(request)
        return httpx.Response(200, json={})

    async def exercise():
        async with carrier.Client(token="token", transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(carrier.UnsupportedFeatureError):
                await client.send("must not go to saved recipient", to="b")
            with pytest.raises(carrier.UnsupportedFeatureError):
                await client.wait(reply_to=1)
        assert writes == []

    asyncio.run(exercise())


def test_credential_identity_is_verified_before_mutation(tmp_path):
    credentials = tmp_path / "identity.json"
    credentials.write_text(json.dumps({"address": "expected", "token": "private-token"}))
    paths = []

    def respond(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"address": "wrong"})

    async def exercise():
        async with carrier.Client(credentials=credentials, transport=httpx.MockTransport(respond)):
            pytest.fail("must reject mismatched identity")

    with pytest.raises(carrier.AuthenticationError):
        asyncio.run(exercise())
    assert paths == ["/whoami"]


def test_failed_send_is_not_automatically_retried_and_error_is_typed():
    writes = []

    def respond(request):
        if request.url.path == "/whoami":
            return httpx.Response(200, json={"address": "a"})
        writes.append(request)
        raise httpx.ReadTimeout("lost response")

    async def exercise():
        async with carrier.Client(token="private-token", transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(carrier.TransportError) as error:
                await client.send("work", idempotency_key="saved-before-send")
            assert "private-token" not in str(error.value)
        assert len(writes) == 1
        with pytest.raises(carrier.CarrierError, match="closed"):
            await client.whoami()

    asyncio.run(exercise())


@pytest.mark.parametrize("status,error", [(401, carrier.AuthenticationError), (503, carrier.HTTPError)])
def test_wait_does_not_hide_service_errors(status, error):
    async def exercise():
        async with carrier.Client(token="token", transport=httpx.MockTransport(lambda request:
            httpx.Response(200, json={"address": "a"}) if request.url.path == "/whoami" else
            httpx.Response(status, json={"detail": "unavailable"}))) as client:
            with pytest.raises(error):
                await client.wait(timeout=0.1)

    asyncio.run(exercise())
