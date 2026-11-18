# Send a verified Skill Manager result

Use this pattern to hand off a verified local result through Carrier.
Run from the Carrier checkout with [Manager Suite dependencies](../integrations/manager-suite.md#prepare-the-optional-examples)
and [example service setup](../guides/example-setup.md). No model account is used.

```mermaid
flowchart TB
  accTitle: Send a verified Skill Manager result
  accDescr: The application prepares and checks the manager result, persists a delivery intent, sends through Carrier, and archives at the receiving inbox before acknowledgment.
  Skill[Skill Manager] -->|Selected script| App[Application executes fixture]
  App -->|Checked total and digest| Intent[Saved delivery intent]
  Intent --> Carrier[Carrier inbox]
  Carrier --> Archive[Commit archive then ack]
```

## Prepare and send

Choose a fresh work directory and a task ID for this logical handoff:

```sh
python examples/manager_handoff.py prepare --kind skill \
  --task-id skill-001 --work .carrier/managers/skill-001
```

The application runs the selected trusted fixture and checks `total: 150`. Skill Manager selects files; it does not execute them. The payload includes the script digest and checked report.

The command prints a numeric `message_id`, `kind: manager.skill` and
`status: stored`. Inspect `delivery.json` in the work directory: it contains the
exact destination, content and retry key saved before sending. It contains no
Carrier token. It may contain task data, so keep it private.

## Accept the handoff

With no other consumer on `sdk/build-events`:

```sh
python examples/archive_events.py
```

For an otherwise empty inbox, expect `Accepted 1 pending event(s)`. The archive
commits the received bytes before acknowledgment. Inspect its `events.content`
column to confirm `type: manager.skill` and the expected result above.

## Recover without repeating preparation

```sh
python examples/manager_handoff.py retry --work .carrier/managers/skill-001
python examples/archive_events.py
```

The retry returns the original message ID and `status: acknowledged`; the second
archive run accepts zero events. If the first send failed after saving intent,
retry that same work directory with the same sender and service URL. Do not
regenerate resources or change the task merely because a response was lost.

Stop example consumers before the service. Retain the work directory, database,
credentials and archive for recovery; remove only disposable example files when
finished. For a new logical task use a new task ID and work directory.

Source: [manager handoff program](../../examples/manager_handoff.py).
