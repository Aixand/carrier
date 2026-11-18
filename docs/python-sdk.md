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

## Identity and setup

Install the SDK in [your application environment](getting-started/install.md#install-the-python-sdk).
Use [shared example setup](guides/example-setup.md) for the supplied scripts.
The optional [Manager Suite integration](integrations/manager-suite.md) has its
own dependencies; core messaging does not require managers or a provider runtime.

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

Use the [example catalog](examples/README.md) for runnable workflows and expected
results. Start with [shared setup](guides/example-setup.md).

### Request a CI report from a worker

[Request a CI report](examples/request-report.md) covers JSON requests, a local
consumer, stable reply keys and correlated responses.

### Publish build events safely across retries

[Retry-safe publishing](examples/retry-safe-send.md) retains the same payload and
key across producer invocations.

### Recover an inbox and archive its events

[Offline recovery](examples/offline-recovery.md) commits an archive row before
acknowledgment and scans pending pages from zero on each invocation.

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
