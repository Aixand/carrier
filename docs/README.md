# Find the right Carrier guide

These docs describe Carrier's development branch. Local source setup requires
Python 3.11+ and a `../aixand-libraries/filesystem` checkout. Native artifacts require
qualification on each advertised platform before publication.

Documentation standard: 0.1.0.

## Choose a reader goal

| I want to… | Start here |
| --- | --- |
| Understand Carrier and exchange my first message | [Project overview and quick start](../README.md#quick-start) |
| Install from source or build a portable product | [Installation](installation.md) |
| Integrate messaging into a Python application | [Python SDK and runnable examples](python-sdk.md) |
| Launch a Codex conversation with Carrier | [Optional agent launch adapter](agent-manager.md) |
| Connect an agent through MCP | [MCP setup](../README.md#mcp) |
| Look up CLI options and state locations | [CLI reference](cli.md) |
| Understand service and consumer responsibilities | [Architecture](../README.md#architecture) · [Delivery semantics](../README.md#delivery-semantics) |
| Diagnose errors or recover a local service | [Troubleshooting](troubleshooting.md) |
| Change Carrier and run local checks | [Development](development.md) · [Participation policy](../CONTRIBUTING.md) |
| Validate an installer artifact | [Installer validation](installer-validation.md) |
| Report a vulnerability or get support | [Security](../SECURITY.md) · [Support](../SUPPORT.md) |
| Publish a Python package from a version tag | [PyPI releases](releases.md) |
| Review changes and licensing | [Changelog](../CHANGELOG.md) · [License](../LICENSE) · [Notices](../NOTICE) |

## Maintain these docs

Authors follow the [documentation standard](_standards/README.md).
The [development guide](development.md#check-documentation) owns local validation
and diagram rendering commands. The checker validates repository Markdown;
examples, external destinations, and publishing renderers need separate verification.

Carrier's implementation owns its service, CLI, SDK, and MCP contracts.
Other applications own consumer scheduling, side effects, and agent launch.
Local checks do not configure repository protections, publish packages, or deploy
hosted installers.
