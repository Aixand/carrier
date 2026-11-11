# Carrier Python SDK

[Project overview](../README.md)

Use Carrier to exchange durable messages between Python applications, background
workers, and agent conversations. These examples use the public async SDK and
run against a local service with separate identities.

**Contents** · [Setup](#identity-and-setup) · [Examples](#runnable-examples) ·
[Consumers](#local-consumers) · [API](#messaging-api) ·
[Retries and errors](#retry-and-compatibility-contract) · [Delivery targets](#composing-delivery-targets)

For the standalone CLI and service, use the
[standalone installer](../README.md#installation).
Python applications need Carrier in their own environment; the CLI's private
environment does not make `import carrier` available elsewhere.

For these examples, install the published beta into a Python 3.11+ virtual
environment. Run from the repository root to use the included examples. Pip installs the
published `aixand-lib-filesystem` dependency automatically:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install aixand-carrier-mcp==0.1.0b0
```

The distribution is `aixand-carrier-mcp`; the import is `carrier`. The service, CLI,
MCP adapter, and SDK ship together. Upgrade the service as well as the client to
use addressed sends and replies. No agent runtime is needed for these examples.

On Windows, use PowerShell with `py -3 -m venv .venv`, then
`.venv\Scripts\python.exe -m pip install aixand-carrier-mcp==0.1.0b0`.
Activate with `.venv\Scripts\Activate.ps1`, or invoke scripts with the environment's
Python and use `.venv\Scripts\carrier.exe` for CLI commands.
For local source development, use `python -m pip install .` from the Carrier
repository root instead of the published package specifier.
See [troubleshooting](troubleshooting.md) if installation fails.

## Identity and setup

Run all commands from the repository root. Provision these identities **once**,
then start the service in the first terminal:

```sh
carrier session sdk/requester --db .carrier/sdk/carrier.db --credentials .carrier/sdk/requester.json
carrier session sdk/report-worker --db .carrier/sdk/carrier.db --credentials .carrier/sdk/worker.json
carrier session sdk/build-events --db .carrier/sdk/carrier.db --credentials .carrier/sdk/events.json
carrier serve --db .carrier/sdk/carrier.db --port 8877
```

The examples use port **8877** and `.carrier/sdk/`, separate from the README's
quick start and the default service database. Keep the database and credentials
when restarting; provisioning refuses to overwrite existing credential files.
The `.carrier/` directory is ignored by Git. Activate the same virtual environment
in each additional terminal.

Each script accepts `--url` and `--credentials` to use another installation.
Provisioning and serving must use the same database. Only one active receiving
owner should use an inbox at a time; the report worker and event archiver have
separate inboxes.

`Client(url=..., credentials=...)` loads an existing address/token file and checks
that the token authenticates that address. Alternatively, supply `token=...` alone.
Opening is lazy or explicit with `await client.open()`; use an async context manager
for HTTP connection cleanup. `connect(to)` selects a default recipient; it does
not open the HTTP client. A closed client cannot be reused.

Each independent agent conversation needs its own credentials. A programmatic
service can retain its identity across restarts. Addresses are permanent; display
names are non-unique, case-sensitive labels. Exact addresses take precedence.
Carrier does not maintain presence, consumer registrations, or delivery-target types.

## Runnable examples

| Use case | Runnable source | SDK features |
| --- | --- | --- |
| Ask a background worker to summarize CI results | [Requester](../examples/request_report.py) · [Worker](../examples/report_worker.py) | JSON messages, correlated replies, async consumers |
| Publish build events, including while a recipient is offline | [Event publisher](../examples/publish_build_event.py) | Stable retry keys, delivery status, typed errors |
| Catch up after downtime without duplicating archived events | [Event archiver](../examples/archive_events.py) | Pending-message pagination, durable processing, explicit acknowledgment |

### Request a CI report from a worker

Use this pattern when a dashboard, coordinator, or agent-facing application needs
a result from another program. The worker returns a summary of named CI checks;
the requester waits for the reply to its specific message.

In a second terminal, start the worker:

```sh
python examples/report_worker.py
```

Expect `Listening as sdk/report-worker; press Ctrl+C to stop.` Leave it running.
In a third terminal, request a report:

```sh
python examples/request_report.py --build-id build-1842
```

The requester sends sample lint, unit, and integration check results and prints:

```json
{
  "build_id": "build-1842",
  "checks": 3,
  "failed": [
    "integration"
  ],
  "status": "failed"
}
```

The sample contains one failed check, so `failed` is the report's expected result.
Replace the `checks` mapping in the requester with results from your own CI job.

With a connected client named `inbox`, the core calls inside an async function are:

```python
question = await inbox.send_json(
    {"build_id": "build-1842", "checks": {"lint": "passed", "integration": "failed"}},
    to="sdk/report-worker",
)
answer = await inbox.wait_for_reply(question, timeout=30)
print(answer.json())
await answer.ack()
```

The full requester also supplies a retry key for its send. The worker registers
an `@inbox.consumer()` handler, sends `message.reply_json()`, and explicitly calls
`message.ack()`. `await inbox.run()` keeps receiving until stopped. The requester
acknowledges the reply after displaying it. The worker's reply key is derived
from the incoming numeric message ID, so retrying that handler with the same
report does not store a second reply.

To try offline delivery, stop the worker with Ctrl+C, run another request, then
restart the worker before the requester's 30-second deadline. The stored request
is still available. `--timeout 5` gives a shorter wait; a timeout ends the local
wait without canceling the stored request. It prints the request ID so you can
later inspect `receive(reply_to=...)` history. Each invocation creates a new
request and retry key; rerunning this script is a new request, not recovery of
the previous one. The next example shows how to reuse a key across invocations.

### Publish build events safely across retries

Use this pattern for CI notifications or application events whose recipients may
be offline. The build system supplies a stable build ID, allowing a restarted
producer to reconstruct the same event key and payload.

No event consumer needs to be running. Publish the same completed build twice:

```sh
python examples/publish_build_event.py build-1842 --status passed
python examples/publish_build_event.py build-1842 --status passed
```

Both calls print the **same numeric message ID** with status `stored`. Only one
message is stored in `sdk/build-events`. The key is `build.finished:build-1842`;
it is independent of the report requests from the previous example.

Inside the publisher's async function, the SDK calls are:

```python
key = "build.finished:build-1842"
message = await inbox.send_json(
    {"type": "build.finished", "build_id": "build-1842", "status": "passed"},
    to="sdk/build-events",
    idempotency_key=key,
)
status = await inbox.delivery_status(key)
print(message.id, status["status"])
```

If a transport error leaves delivery uncertain, rerun the
same command with the same credentials, build ID, status, and recipient. The
script reports the uncertainty; the SDK does not automatically replay the send.
Changing the status for an existing key produces a `ConflictError`, which the
script explains. Use a new build ID for a new event.

Keep the payload stable on retries: adding the current time or generating a new
key on every invocation would change this behavior. In an application, retain
the original event data in your own durable storage. `stored` confirms Carrier
has the event; it does not mean a recipient has handled it.

### Recover an inbox and archive its events

Use this pattern for a local event journal or an integration that catches up
after downtime. It saves each message into a separate SQLite archive and commits
that transaction **before** acknowledging the Carrier message.

After publishing the event above, run:

```sh
python examples/archive_events.py
```

For a fresh example inbox, expect:

```text
Accepted 1 pending event(s); archive: .carrier/sdk/event-archive.db
```

Run it again and the count is zero. Repeating the publisher's original command
reports that same message as `acknowledged`; it does not enqueue a new event.
The archive preserves the sender, content, timestamp, and Carrier message ID.

To exercise pagination, publish three new builds and use two-message pages:

```sh
python examples/publish_build_event.py build-1843
python examples/publish_build_event.py build-1844 --status failed
python examples/publish_build_event.py build-1845
python examples/archive_events.py --page-size 2
```

Expect `Accepted 3 pending event(s)` on the final run. The archiver follows
`next_after` within that scan and starts at zero on each new invocation. It does
not persist the pending-page cursor, so an older unacknowledged message is still
eligible after recovery.

The archive key combines the backend URL, inbox address, and message ID. If the
process stops after committing the row but before acknowledging it, the next run
finds the same pending message, reuses the archived row, and acknowledges it.
Keep using the same archive and backend database across restarts; if you replace
the backend database, choose a fresh `--archive` path because IDs may be reused.

This example makes local archive inserts safe to repeat. Carrier cannot make
unrelated API calls or other application side effects exactly once. For those,
use the destination's own idempotency support or a durable record of work.

## Local consumers

The [report worker](../examples/report_worker.py) is a complete consumer example.
The decorator registers one local async function; `run()` performs receiving
until cancelled or an error occurs. Alternatively, pass any async callable to
`await inbox.consume(handler)`. Neither form starts a hidden thread, daemon,
service, or agent. Run consumers for independent inboxes concurrently with
`asyncio.TaskGroup` or `asyncio.gather`.

The consumer loop is sequential with at most one message in flight. Every handler must
call `await message.ack()` explicitly. Returning without it raises
`UnacknowledgedMessage` and stops consumption. A handler exception, service error,
or cancellation also stops consumption. Unacknowledged messages remain pending;
an acknowledgment already confirmed is not undone by a later exception. No handler
or mutation is automatically retried. Cancel and await the consumer task before closing
its client. Application retry policy belongs outside the consumer loop.

The report worker expects the requester's JSON schema. Invalid JSON or missing
fields stop it and leave the message pending. Applications should validate their
message protocol and decide how to record or route rejected requests.

Run only one active receiving owner per inbox. Carrier's reads are non-destructive
and do not claim messages; different clients/processes can see the same pending
message. This release has no distributed consumer leases, competing-worker queue,
automatic dead-letter handling, or exactly-once application effects. Use message
IDs to deduplicate your own persistence/API operations. Acknowledgment means the
consumer accepted responsibility, not that a task succeeded.

## Messaging API

| Method | Result / behavior |
| --- | --- |
| `whoami()`, `list_sessions(after="", limit=50)`, `rename(name)` | Identity/directory dictionaries. |
| `send(content, to=None, reply_to=None, idempotency_key=None)` | Stored `Message`; explicit addressing is atomic and does not change the default recipient. |
| `send_json(value, ...)` | JSON serialized into the ordinary text body, with the same send options. |
| `receive(after=0, limit=50, reply_to=None)` | `MessagePage` containing history, including acknowledged messages. |
| `receive_sent(after=0, limit=50, reply_to=None)` | This identity's retained outgoing history, including sends made by other clients. Requires the service’s `/sent` endpoint. |
| `receive_pending(after=0, limit=50, reply_to=None)` | `MessagePage` containing only pending messages. |
| `wait(timeout=45, limit=50, poll_interval=0.5, reply_to=None)` | `WaitResult`: `status` is `messages` or `timeout`, plus `messages` and `next_after`. |
| `wait_for_reply(sent_message, timeout=45, poll_interval=0.5)` | First pending correlated reply; raises `TimeoutError` on deadline. Does not acknowledge it. |
| `ack(message_id)` | Idempotent acknowledgment of a numeric inbox message ID. |
| `delivery_status(idempotency_key)` | Dictionary reporting `stored` or `acknowledged` for your keyed send. |

Messages expose `id`, `sender`, `recipient`, `content`, `created_at`,
`idempotency_key`, `reply_to`, and `acknowledged_at`. `message.json()` explicitly
decodes JSON; arbitrary text is never decoded automatically. `message.reply()` and
`reply_json()` send to the original sender with `reply_to=message.id`; neither
acknowledges the original. `message.ack()` updates its local acknowledgment field.
Inside a consumer handler, use this method so the consumer loop can verify acceptance.

`receive_pending` pagination is a scan, not a permanent cursor. Follow
`next_after` within one scan; start each new scan at zero so older pending messages
aren't lost. `receive` has the legacy history cursor semantics. `wait` polls
asynchronously and never blocks the event loop. Network/authentication errors are
errors, not empty inboxes or normal wait timeouts. The HTTP request timeout defaults
to 15 seconds and can be configured with `request_timeout`.

Replies are ordinary messages. The service validates that a reply references a
message in the sender's inbox and is addressed back to its original sender. It
does not require one reply per question or interpret task completion. Acknowledged
replies remain accessible with `receive(reply_to=question.id)`.

## Retry and compatibility contract

`idempotency_key` maps to the existing HTTP/MCP string `message_id`; the numeric
`id` identifies a stored message. These are distinct. Persist the retry key before
a send when recovery is required. Without a key, repeated calls can create duplicates.

An explicit send pins its original requested destination and resolved address.
Repeating its key, body, destination, and `reply_to` returns the original, even if
the display name is renamed or reassigned. Retrying with that original resolved
address is also accepted. Changing the payload, explicit destination, correlation,
or switching between implicit and explicit addressing produces HTTP 409.
Legacy unaddressed sends retain their old retry semantics: changing the saved
recipient after a send does not reroute a retry of the original key.

The SDK checks `/capabilities` before using addressed sends or reply correlation.
An older backend cannot silently ignore `to` and deliver to an old selected
recipient. Legacy operations still work against an older service. Recreate a
client after upgrading a service if it has cached old capabilities.

Errors derive from `CarrierError`: `HTTPError` retains `status_code` and `detail`,
with `AuthenticationError` and `ConflictError` specializations; `TransportError`
means no response was confirmed; `ProtocolError` means an invalid response;
`UnsupportedFeatureError` requests an upgrade. A send/ack may have taken effect
despite a transport error or cancellation. No automatic mutation replay occurs.

The MCP adapter uses the same SDK. Its existing tools and argument names remain;
`send` gains optional `to` and `reply_to`, while `receive`, `receive_pending`, and
`wait` gain optional `reply_to` filtering. MCP `wait` retains its 300-second maximum.
Restart existing MCP adapters to load the new tools.

## Composing delivery targets

A consumer can await database operations, HTTP APIs, a workflow executor, or an
agent runtime input API. These dependencies belong to the application.
Carrier does not import or inspect them.

For an agent target, accept the Carrier message after confirmed input delivery,
track uncertain delivery separately, and serialize input using the runtime's
readiness observations. The agent explicitly sends its answer through Carrier.
Runtime readiness is not proof that the question was answered. Choose either an
application inbox consumer or agent-side `wait`/`receive`, not both independently.

Start with the local [report worker](../examples/report_worker.py) for an
application-owned consumer and [event archiver](../examples/archive_events.py)
for a durable recovery journal. Integrating an agent session requires
application-owned delivery and recovery logic. Agent launch/tool configuration
is separate from the messaging SDK. The [optional agent launch adapter](agent-manager.md)
provides launch/binding coordination without adding `bind_agent` to the core inbox
client. Execution remains the responsibility of the external runtime.
