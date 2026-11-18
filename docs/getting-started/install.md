# Install Carrier for your application

Choose the native CLI/service for running Carrier, or the Python package for
code that imports its SDK. They have separate environments.

| Need | Install |
| --- | --- |
| Run `carrier serve` or an MCP adapter | Native CLI and service |
| Import `carrier.Client` in Python | Package in your application's Python 3.11+ environment |
| Change Carrier or build native artifacts | [Development](../development.md) · [Product installation](../installation.md) |

## Install the native CLI

For the documented `0.1.0-beta` release, Linux x64 GNU and macOS Intel/ARM64 use:

```sh
curl -fsSL https://installer.aixand.org/carrier | sh
carrier --version
carrier --help
```

Confirm the terminal prompts. The installer verifies the selected native archive
and includes a private Python runtime. No system Python, uv or compiler is needed.
If the command is missing, check `~/.local/bin` in PATH and any command setup preserved.

On Windows x64 in PowerShell 5.1+:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri 'https://installer.aixand.org/carrier/install.ps1' -OutFile install-carrier.ps1
.\install-carrier.ps1
carrier --version
```

Open a new terminal for PATH changes. Local script execution policy applies.
Installation starts no service. Run `carrier serve` explicitly, or continue with
[the isolated quick start](../quickstart.md).

## Install the Python SDK

From your application's directory, use a Python 3.11+ environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install aixand-carrier-mcp==0.1.0b0
python -c 'from carrier import Client; print(Client.__name__)'
```

On Windows use `py -3 -m venv .venv`, `.venv\Scripts\Activate.ps1`, and the
same `python -m pip` command. The import check prints `Client`.
The distribution is `aixand-carrier-mcp`; its import and CLI are `carrier`.
The native CLI's private environment does not add Carrier to your application.

## Work from source

Run `python -m pip install .` from the Carrier checkout in the chosen environment.
Pip resolves the published filesystem library automatically. Developer helpers
and packaging use the [sibling source prerequisites](../installation.md#source-checkout-prerequisites).
Use [example setup](../guides/example-setup.md) when running repository scripts.

## Update, repair, and remove

Keep your database and credentials separate from software payloads. Software
removal preserves them. Stop database writers and back up state before upgrades
or moves. See [operations](../guides/operations.md) and
[product lifecycle](../installation.md#update-repair-and-remove) for maintainer procedures.
