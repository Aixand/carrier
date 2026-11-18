# Connect an agent through MCP

## Prepare two inboxes

Complete the [quickstart](../quickstart.md) setup to create `demo/requester` and `demo/reviewer`, then keep its service running on port 8876. Use an MCP-capable app. Each app owns its configuration format; the example below uses an `mcpServers` object.

## Configure the adapter

Configure a stdio MCP adapter for each agent conversation, using absolute paths.
This example connects to the quick-start requester's inbox:

```json
{
  "mcpServers": {
    "carrier": {
      "command": "/home/you/.local/bin/carrier",
      "args": [
        "mcp", "--url", "http://127.0.0.1:8876",
        "--credentials", "/absolute/path/to/carrier/.carrier/requester.json"
      ]
    }
  }
}
```

Replace the command with the absolute path to your installed `carrier` and the
credentials path with your own. The configuration format depends on your app.
Each independent conversation needs its own identity. The shared backend is an
HTTP service; the local adapter
provides the MCP tools. An agent can call
`send(to="demo/reviewer", content="Can you review this change?")`, then use
`wait()` to receive messages and `ack()` to accept them.

For the receiving conversation, use `reviewer.json`. Let the agents own their
inbox reads once connected. To correlate a reply, send it back to the original
sender with `reply_to` set to the received message's numeric `id`. The requester
can then call `wait(reply_to=...)` with its original request's ID.

`wait()` defaults to 45 seconds and accepts `timeout_seconds` up to 300. Keep
your app's MCP tool timeout above that duration. Waiting does not acknowledge
messages; call `ack(message_id=...)` after accepting each one. Reconnect the
adapter after upgrading Carrier to load updated tools.

The Python SDK calls the send retry key `idempotency_key`; MCP calls it
`message_id`. Acknowledgments use the stored message's numeric `id`.

## Check the connection

Before opening the agent app, run this from the Carrier repository root:

```sh
carrier check --url http://127.0.0.1:8876 --credentials .carrier/requester.json
```

Expect the authenticated requester identity. If it fails, check the service URL and existing credential file before changing the app configuration.

Then follow the [two-inbox MCP exchange](../examples/mcp-exchange.md) to verify tool delivery.

## Stop and resume

Close the app's MCP connection before stopping the service with Ctrl+C. Keep the database and credential files. Reopen adapters after an upgrade so they load the current tools.
