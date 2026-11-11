import asyncio
import carrier
import httpx
from carrier.service import Store, create_app


def test_sent_history_is_authenticated_sender_scoped_and_retained(tmp_path):
    path = str(tmp_path / "carrier.db")
    store = Store(path)
    tokens = {name: store.provision(name) for name in ("a", "b", "c")}
    app = create_app(path)
    async def run():
        def client(name):
            return carrier.Client(url="http://carrier", token=tokens[name], transport=httpx.ASGITransport(app=app))
        async with client("a") as a, client("b") as b, client("c") as c:
            first = await a.send("one", to="b", idempotency_key="one")
            await a.send("two", to="c")
            reply = await b.send("answer", to="a", reply_to=first.id)
            await b.ack(first.id)
            page = await a.receive_sent(limit=1)
            assert page.messages[0].id == first.id
            assert page.messages[0].acknowledged_at is not None
            tail = await a.receive_sent(after=page.next_after)
            assert [m.content for m in tail.messages] == ["two"]
            assert [m.id for m in (await b.receive_sent(reply_to=first.id)).messages] == [reply.id]
            assert (await c.receive_sent()).messages == []
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://carrier") as raw:
                assert (await raw.get("/sent")).status_code == 401
    asyncio.run(run())
