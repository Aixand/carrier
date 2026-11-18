# Look up the HTTP contract

All routes except `/health` require `Authorization: Bearer TOKEN`.
The SDK and MCP tools use these same service operations.

| Route | Input or filter | Result |
| --- | --- | --- |
| `GET /health` | None | `status: ok`, `service: carrier` |
| `GET /capabilities` | None | Protocol 1; `addressed_send`, `reply_to` |
| `GET /whoami` | None | Address, name and default recipient |
| `GET /sessions` | `after` address; `limit` 1–100, default 50 | Directory page; terminal `next_after: null` |
| `POST /rename` | `name` string or null | Updated own display name |
| `POST /connect` | `to` | Saved default recipient |
| `POST /send` | `content`; optional `to`, `reply_to`, `message_id` | Stored message, including retry reuse |
| `POST /ack` | Numeric `message_id` | Idempotent acknowledgment of own inbox message |
| `GET /delivery_status` | String `message_id` retry key | Own send: `stored` or `acknowledged` |
| `GET /receive_pending` | `after`, `limit`, optional `reply_to` | Pending page; terminal `next_after: null` |
| `GET /receive` | Same filters | Incoming history; cursor is last ID or the supplied `after` |
| `GET /sent` | Same filters | Own outgoing history with the same history cursor behavior |

`after` is nonnegative and message filters use positive IDs. Message page limits
are 1–100, default 50. Do not treat history cursors as nullable pending cursors.
The ordinary message body is text; JSON is an application convention.

## Distinguish IDs and limits

| Value | Limit or meaning |
| --- | --- |
| `content` | 1–100,000 characters |
| Explicit `to` and retry key | 1–200 characters |
| Display name | 1–80 printable characters; no outer whitespace; null clears it |
| Numeric `id` | Stored record identity used by `reply_to` and `/ack` |
| String `message_id` | Sender retry key; Python names it `idempotency_key` |

## Interpret failures

| Status | Check |
| --- | --- |
| 401 | Restore the matching database and credentials |
| 404 | Check recipient, reply parent, own inbox or keyed send |
| 409 | Resolve name ambiguity, missing default recipient, reply destination or changed retry intent |
| 422 | Check field sizes, IDs, limits and request validation |

A lost response does not prove a failed mutation. Keep the original bytes and key;
read [recovery](../lifecycles/delivery.md). `/sent` requires a service version that
implements it; a 404 from an older service is an error, not an empty outbox.
Budget endpoints have a [separate contract](budget.md).

Sources: [route definitions](../../carrier/service.py), [SDK errors](../../carrier/errors.py).
