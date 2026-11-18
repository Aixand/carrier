# Send your first request and reply

Follow [installation](getting-started/install.md) first. Use the SDK virtual environment in every terminal. These instructions describe the current source checkout.

Exchange a request and reply between two inboxes. This walkthrough uses
`.carrier/demo.db` and port **8876**, separate from the service's default
database and port. Run commands from the repository root.

1. **Create the two identities once.**

   ```sh
   carrier session demo/requester --db .carrier/demo.db --credentials .carrier/requester.json
   carrier session demo/reviewer --db .carrier/demo.db --credentials .carrier/reviewer.json
   ```

   Each command prints `Created ...; credentials saved to ...`. Keep those
   credential files to reuse the inboxes; provisioning refuses to overwrite
   them. The `.carrier/` directory is ignored by Git.

2. **Start the shared service.**

   ```sh
   carrier serve --db .carrier/demo.db --port 8876
   ```

   Leave this terminal running. In a second terminal, verify the service:

   ```sh
   carrier status --url http://127.0.0.1:8876
   ```

   Expect `Carrier running at http://127.0.0.1:8876`.

3. **Send, reply, and acknowledge.**

   Save the following as `.carrier/exchange.py` and run
   `.venv/bin/python .carrier/exchange.py` from the repository root, using the
   SDK environment created during installation:

   ```python
   import asyncio
   from uuid import uuid4

   from carrier import Client

   async def main():
       url = "http://127.0.0.1:8876"
       async with (
           Client(url=url, credentials=".carrier/requester.json") as requester,
           Client(url=url, credentials=".carrier/reviewer.json") as reviewer,
       ):
           retry_key = uuid4().hex
           question = await requester.send(
               "Can you review this change?",
               to="demo/reviewer",
               idempotency_key=retry_key,
           )
           page = await reviewer.receive_pending()
           incoming = next(m for m in page.messages if m.id == question.id)
           print("Reviewer received:", incoming.content)
           await incoming.reply("I'll review it.")
           await incoming.ack()

           answer = await requester.wait_for_reply(question, timeout=5)
           print("Requester received:", answer.content)
           await answer.ack()
           status = await requester.delivery_status(retry_key)
           print("Request delivery:", status["status"])

   asyncio.run(main())
   ```

   Expected output:

   ```text
   Reviewer received: Can you review this change?
   Requester received: I'll review it.
   Request delivery: acknowledged
   ```

The example opens both inboxes in one program; each can instead belong to a
separate application or agent. Use these demo inboxes without other active
consumers. Each successful run acknowledges both messages, and a new run uses a
fresh retry key. Acknowledgment records acceptance of the request; the review
itself is application work.

Stop the service with **Ctrl+C**. Restart it with the same database and reuse the
credential files to retain identities and history. For normal operation, the
defaults are `http://127.0.0.1:8765` and `~/.aixand/carrier/carrier.db`.
Carrier creates its per-user directory, `~/.aixand/carrier`, when needed.
Override the database with `--db`; provisioning and serving must use the same
database. Credential files remain at the explicitly supplied `--credentials` path.

Existing databases at `~/.local/share/carrier/carrier.db` are not moved
automatically. To migrate, stop the service and other processes accessing the
database, then move `carrier.db` and any SQLite sidecar files into
`~/.aixand/carrier/`, without overwriting an existing database. Keep your credential
files and update any explicit database paths in service units or integrations
before restarting. To continue using the previous location, pass
`--db "$HOME/.local/share/carrier/carrier.db"` to both provisioning and serving.
