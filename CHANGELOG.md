# Changelog

User-visible changes to Carrier are recorded here. Entries under
Unreleased describe changes that have not yet appeared in a published release.

Entries use the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.

## Unreleased

## 0.1.0b0 - 2026-11-11

Initial beta release, published as `aixand-carrier-mcp` on PyPI.

### Added

- Durable SQLite inboxes, authenticated messaging, correlated replies, retry keys,
  and explicit acknowledgments through the async Python SDK, CLI, and MCP adapter.

- Tag-triggered PyPI publishing with version checks, distribution validation,
  registry dependency installation, and Trusted Publishing.

- Independent documentation, repository policy, and secret-scanning CI workflows.

- Apache-2.0 licensing and package metadata, contribution and security policies,
  support channels and issue templates.
- Documentation standard 0.1.0, a documentation index, CLI reference,
  troubleshooting, and local documentation and repository policy checks.

### Changed

- The Python distribution is named `aixand-carrier-mcp`; the import and CLI
  remain `carrier`.

- Shared Python library distribution names use the `aixand-lib-` prefix.
  Python import names are unchanged.

- Participation policy accepts issues; external pull
  requests are not accepted. Unused DCO tooling and the pull request template
  are removed.
- Documentation uses task guidance instead of dated update notes and historical
  installer test counts.

### Fixed

- Protect CLI and SDK credential files with Windows ACLs as well as Unix modes.
- Native installer CI uses the library repository by default, provisions Python
  with uv, and consumes the dependency lock without optional source checkouts.

- Ignore local environment files, private keys, Python bytecode, and editor artifacts
  while keeping sanitized environment examples available.

- Source setup reports a missing `aixand-libraries/filesystem` checkout before invoking
  source installation. Artifact operations and uninstall do not need that source.
- SDK setup installs the required local filesystem package explicitly. Documentation
  resolves the published filesystem dependency automatically; development helpers
  and native packaging retain the paired source checkout requirement.
- Native packaging uses the locked wheel-tag tooling and works in uv environments
  that do not contain pip.
- Upgrade qualification changes both the product and Python package versions,
  allowing the same-version protection to remain enforced during a real upgrade.
