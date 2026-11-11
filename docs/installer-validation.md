# Validate a Carrier installer artifact

Use this guide to assess a revision-2 installer artifact before publication.
Run the [build and verification procedure](installation.md#build-and-verify)
from the Carrier repository root. It requires the paired filesystem sources,
locked build tools, network access for packaging, and a native build host.

## Check lifecycle behavior

[qualify_installation.py](../scripts/qualify_installation.py) copies the portable
consumer outside the checkout and uses temporary installation paths. It checks
installation with language tools absent from PATH, blocked dependency downloads,
and invalid Python environment overrides.

The installed product check provisions temporary identities, starts a loopback
HTTP service, exchanges messages, verifies retry and acknowledgment behavior,
reuses credentials, and stops the service. The lifecycle check also covers:

- Independent shared and private installations and owner conflicts.
- Resuming a request with the same request ID and reinstalling.
- Rejection of a damaged upgrade and generic stateful rollback.
- Uninstall after stopping the service, with database and credential preservation.

`--build-upgrade` builds a next-version artifact in disposable sources and checks
that upgrade retains the database and identities. Use `--upgrade-artifact PATH`
instead to test a supplied candidate. These options are mutually exclusive.

`--bootstrap PATH` checks the generated first stage with Python absent from PATH.
This check downloads its checksum-pinned helper interpreter; offline product
installation and first-stage bootstrap are separate checks.

## Read the result

A successful lifecycle run exits zero and prints JSON containing `verified: true`.
When `--report PATH` is supplied, the report is also written to that new file.
Inspect `target`, `manifest_sha256`, `upgrade_tested`, and
`bootstrap_without_system_python` to identify the artifact and optional coverage.
An omitted optional check does not count as a pass.

If a check fails, inspect its error and rerun against a newly built artifact after
resolving the cause. Keep reports with the matching artifact and source revision.
Store execution logs and test counts in build artifacts or review reports rather
than maintaining them as product documentation.

## Qualify native releases

A local Linux result does not qualify Windows, macOS, Linux ARM64, or an older
operating system. Run the [native installer workflow](../.github/workflows/installer.yml)
on each advertised target and verify clean-machine and minimum-OS behavior.
`AIXAND_LIBRARIES_REPOSITORY` defaults to `Aixand/aixand-libraries`; override it
for another accessible library repository. `AIXAND_LIBRARIES_REF` selects its
revision for custom runs. The tracked workflow pins its default dependency commit;
release runs require an explicit full commit SHA. The workflow provisions pinned Python through uv
on all targets. Intel macOS builds cryptography from its checksum-verified locked source with
static OpenSSL because upstream no longer supplies Intel macOS wheels.

Qualification reports must match the artifact’s source revision and dependency
layout. Rerun native qualification when either changes.

Exporting a handoff does not publish a release or deploy a hosted installer.
See [publication handoff](installation.md#publication-handoff) for the required
artifact set. Review database compatibility and backup requirements before
shipping schema changes; Carrier has no automatic database rollback adapter.
