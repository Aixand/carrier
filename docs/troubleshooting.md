# Diagnose local Carrier setup and service errors

Use this guide to restore a local development or source installation. Run setup
commands from the Carrier repository root and use the environment containing
the intended Carrier installation.

## Setup cannot find aixand-lib-filesystem

If the helper reports a missing local dependency, or uv reports an editable
distribution missing at `../aixand-libraries/filesystem`, inspect the paired source layout:

```sh
python3 -c "from pathlib import Path; print(Path('../aixand-libraries/filesystem/pyproject.toml').resolve().is_file())"
```

`False` means the required sibling checkout is absent. Obtain its source and
place it alongside Carrier, following [source prerequisites](installation.md#source-checkout-prerequisites).
Then rerun `./dev.sh develop`. The development helpers require that local source.
For SDK use without the helpers, run `python -m pip install .` in your virtual
environment; pip resolves the published filesystem dependency automatically.

## The command or import is missing

If the shell cannot find `carrier`, activate the SDK environment or invoke the
installed command by absolute path. On Linux/macOS, the source installer's
default command is `~/.local/bin/carrier`; the SDK environment uses
`.venv/bin/carrier`. On Windows the SDK command is `.venv\Scripts\carrier.exe`.

If Python cannot import `carrier`, run `python -m pip install .` from the Carrier root using that Python
environment. The standalone CLI's private environment does not make the SDK
available to other applications. Verify the selected interpreter:

```sh
python -c "import sys, carrier; print(sys.executable); print(carrier.__file__)"
```

The printed paths should belong to the environment intended for your application.

## The backend is unavailable

For the README quick start, probe the explicitly selected URL:

```sh
carrier status --url http://127.0.0.1:8876
```

If unavailable, inspect the service terminal for startup errors and confirm its
host and port. Start it with `carrier serve --db .carrier/demo.db --port 8876`
if it is stopped. If the port is already occupied, identify the existing service
before choosing a different port and updating every client's URL.
The default service uses port 8765; the SDK examples use 8877.

## Credentials are rejected or already exist

Check the identity against the service that owns its database:

```sh
carrier check --url http://127.0.0.1:8876 --credentials .carrier/requester.json
```

Success prints the authenticated identity. Failure means the service, database,
or credential pair needs checking. Confirm that provisioning and serving use
the same database and that the credential file belongs to that identity.

An existing credential file is expected on a repeated quick-start run. Reuse it;
do not rerun `carrier session` for the same address. If credentials are lost,
restore their original file from a private backup. A new token cannot authenticate
an existing identity. Choose a new address and credential file only when you
intend to create a separate inbox.

## A consumer stops or a message repeats

Reading does not acknowledge a message. A handler must explicitly call
`await message.ack()` after accepting responsibility. An unacknowledged return,
handler exception, service error, or cancellation stops the SDK consumer loop.
Inspect the error and pending messages before restarting the consumer.

Use one active receiver per inbox. Repeated deliveries require application
deduplication where side effects must be safe to repeat. A stable send retry key
prevents duplicate storage; it does not make application effects exactly once.
See [consumer behavior](python-sdk.md#local-consumers) and
[the archive example](python-sdk.md#recover-an-inbox-and-archive-its-events).

## Preserve data before repair or upgrade

Stop all services and local provisioning processes using the database before
copying or moving it. Preserve `carrier.db` and any `carrier.db-wal` and
`carrier.db-shm` files together. Back up credential files separately and keep
their permissions private. Restore the matching database and credentials to an
unused location, then verify with `carrier status` and `carrier check`.

Software uninstall preserves databases and credentials. Generic product rollback
is rejected for this stateful service; follow [update and removal guidance](installation.md#update-repair-and-remove)
instead. Do not delete a database to repair a Python environment.
