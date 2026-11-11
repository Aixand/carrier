# Carrier CLI reference

Use this reference for local service administration and MCP adapter configuration
on the development branch. Arguments and defaults are defined in
[carrier/cli.py](../carrier/cli.py). Run `carrier --help` or a subcommand's
`--help` for the installed version's exact parser.

## Commands

| Command | Purpose | Required arguments |
| --- | --- | --- |
| `carrier --version` | Print the Carrier version and exit | None |
| `carrier serve` | Start the shared HTTP service | None |
| `carrier session ADDRESS` | Provision a new inbox and write credentials | `ADDRESS`, `--credentials PATH` |
| `carrier budget-source ADDRESS` | Provision a budget monitor with a fixed recipient | `ADDRESS`, `--to ADDRESS`, `--credentials PATH` |
| `carrier status` | Check the backend health endpoint | None |
| `carrier check` | Authenticate an existing credential file and verify its address | `--credentials PATH` |
| `carrier mcp` | Run one stdio MCP adapter with existing credentials | `--credentials PATH` |

## Service and identity options

| Command/option | Default | Meaning |
| --- | --- | --- |
| `serve --db PATH` | `~/.aixand/carrier/carrier.db` | SQLite database for identities and messages |
| `serve --host HOST` | `127.0.0.1` | HTTP bind address |
| `serve --port PORT` | `8765` | HTTP listen port |
| `session --db PATH` | Same database default | Database receiving the new identity |
| `session --name NAME` | No display name | Optional case-sensitive, non-unique display name |
| `budget-source --db PATH` | Same database default | Database containing the existing recipient and new source |
| `budget-source --to ADDRESS` | Required | Exact existing recipient address |

Provisioning and serving must use the same database. Relative paths are resolved
from the process working directory. Addresses are permanent; display names can
change. Provisioning creates credentials exclusively and refuses an existing
file or duplicate address. Reuse existing credentials to resume an identity.

The CLI's `session` command creates a new identity. Applications requiring
recoverable provisioning use the local `ensure_session()` API described in
[the project setup](../README.md#python-sdk-setup).

## Client and adapter options

| Command/option | Default | Meaning |
| --- | --- | --- |
| `status --url URL` | `http://127.0.0.1:8765` | Backend to probe |
| `status --json` | Human-readable output | Print the health result as JSON |
| `check --url URL` | Same URL default | Backend to authenticate against |
| `check --budget-source` | Ordinary session check | Verify a budget-source identity and fixed route |
| `mcp --url URL` | Same URL default | Backend used by the stdio adapter |
| `mcp --binding PATH` | Unset | Optional conversation binding gate |
| `mcp --binding-hook PATH` | Unset | Optional lifecycle handler; requires `--binding` |

Credential files contain the inbox address and bearer token. Keep one file per
independent inbox and use absolute credential and command paths in MCP app
configuration. Conversation binding options belong to that integration; ordinary
standalone MCP setup needs only the URL and credentials.

`status` uses a five-second HTTP request timeout. A healthy backend prints
`Carrier running at URL` and exits zero. An unavailable or incompatible health
response prints `Carrier unavailable at URL` and exits one. JSON output contains
`status` and `url`; it never includes a token.

`check` uses a five-second HTTP request timeout, verifies the credential address,
and prints the authenticated identity on success. Invalid credentials or an
unreachable backend produce an error and nonzero exit. Restore the existing
service/identity rather than creating replacement credentials for the same address.

See [MCP setup](../README.md#mcp) for tool timeouts and reply correlation, and
[the SDK guide](python-sdk.md#messaging-api) for messaging operations.

## Optional agent launch commands

`carrier agent` provides `run`, `start`, `continue`, `adopt`, and `reconcile` through
the optional agent launch adapter. See [setup, arguments and recovery](agent-manager.md).
This subcommand requires the `agent-manager` extra; ordinary Carrier commands do not.
