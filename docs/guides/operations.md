# Operate a local Carrier service

## Start and check the service

After [installation](../getting-started/install.md), run from your Carrier checkout:

```sh
carrier serve
```

The defaults are `http://127.0.0.1:8765` and `~/.aixand/carrier/carrier.db`. In another terminal:

```sh
carrier status
carrier check --credentials /absolute/path/to/existing-inbox.json
```

Replace the credential path with your existing inbox file. Status checks service health; `check` also authenticates the identity. For a custom service, pass the same `--url` to both checks. See [CLI reference](../cli.md).

## Restart while retaining history

Stop consumers and MCP adapters, then stop the service with Ctrl+C. Restart with the same database and reuse the original credentials. Provisioning and serving must point to the same database.

Software installation starts no service. Start `carrier serve` explicitly after installing or updating. Installing the CLI also does not expose its private Python environment to other applications.

## Preserve data before an upgrade

Stop the service and other processes that access its database. Back up the database, any SQLite sidecar files, credentials, and service configuration before changing software or moving data. Keep these files outside versioned software payloads.

The old `~/.local/share/carrier/carrier.db` location is not migrated automatically. Move its database and sidecars only while stopped, without overwriting another database. Update explicit paths, or keep the old location with `--db` on both provisioning and serving.

Generic software rollback does not roll back Carrier's database. Review schema compatibility and restore requirements before upgrading. Uninstall preserves databases and credentials. See [installation lifecycle](../getting-started/install.md#update-repair-and-remove).

## Handle a stopped consumer

A handler failure or missing explicit acknowledgment stops consumption and leaves unacknowledged messages pending. Diagnose the original failure, then restart with the same identity. Use stable application-side deduplication for side effects. See [troubleshooting](../troubleshooting.md#a-consumer-stops-or-a-message-repeats).

## Network scope

The service binds to localhost by default. Remote deployments require HTTPS and operational hardening. These guides demonstrate local operation; a local health check does not establish remote deployment readiness.
