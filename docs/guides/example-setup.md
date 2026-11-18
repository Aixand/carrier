# Prepare the example service

## Prerequisites

Follow [installation](../getting-started/install.md) and activate the SDK environment. Work from the Carrier repository root in every terminal. On Windows, use the environment's Python and Carrier executables.

## Create inboxes and start the service

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

## Check the service

In another terminal with the same environment active, run:

```sh
carrier status --url http://127.0.0.1:8877
carrier check --url http://127.0.0.1:8877 --credentials .carrier/sdk/requester.json
```

The status command prints `Carrier running at http://127.0.0.1:8877`. The identity check authenticates `sdk/requester`.

## Stop and resume

Stop consumers first, then stop the service with Ctrl+C. Keep `.carrier/sdk/` to resume with the same identities, history, and archive. Do not rerun provisioning for existing addresses. If port 8877 is busy, choose another port and pass its URL to every client.
