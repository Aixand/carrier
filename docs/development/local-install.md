# Install a development CLI

Keep the required `../aixand-libraries/filesystem` checkout described under
[installation](../installation.md#source-checkout-prerequisites). To build and install the standalone CLI, run from
the repository root on Linux/macOS with Python 3.11+:

```sh
./dev.sh install --prod
```

On Windows, use PowerShell 5.1+ with Python 3.11+:

```powershell
.\dev.ps1 install --prod
carrier --help
```

The PowerShell script detects `py`, `python`, `python3`, or an existing
uv-managed Python. Set `CARRIER_DEV_PYTHON` to select a specific executable.
It works from any directory and does not require administrator access.
Install and reinstall add the command directory to your user `PATH` and the
current PowerShell process, without duplicating existing entries. Run
`.\dev.ps1` directly to use `carrier` immediately. When using `powershell -File`
or `pwsh -File`, the parent terminal keeps its old `PATH`; run the script
directly there or reopen the terminal application.

The development installer publishes `carrier` (`carrier.exe` on Windows) in
`~/.local/bin` and installs its private environments in
`~/.aixand/carrier/dev-install` by default. On Linux/macOS, add the command
directory to your shell PATH. Virtual environment activation is not needed.

<details>
<summary><strong>Local reinstall, uninstall, and custom paths</strong></summary>

```sh
./dev.sh reinstall
./dev.sh uninstall
```

On Windows:

```powershell
.\dev.ps1 reinstall
.\dev.ps1 uninstall
```

Reinstall builds and checks a fresh environment before switching the command.
Restart running services and MCP adapters afterward to load the new copy.
On Windows, stop them before reinstalling so `carrier.exe` is not in use.
Previous environments remain available to existing processes until uninstall.
Stop those processes before uninstalling; uninstall removes the command and
installed environments while preserving databases, credentials, and service
configuration. The script does not register or manage a background service.
Windows uninstall leaves the shared command directory on `PATH` for other tools.

Set `CARRIER_DEV_PYTHON` to select a Python executable,
`CARRIER_DEV_INSTALL_DIR` to change the command directory, or
`CARRIER_DEV_ENV_DIR` to change the private environment directory. Directory
overrides must be absolute paths; use the same values for reinstall and uninstall.
Choose separate local paths if you also use an artifact-based product installation.
Run `./dev.sh --help` or `.\dev.ps1 --help` for the full command reference.
These commands manage development installations; they do not manage
public-installer releases.

For a development installation using the previous default directory, stop the
service and MCP adapters, then reinstall at the new location:

```sh
CARRIER_DEV_ENV_DIR="$HOME/.local/share/carrier/dev-install" ./dev.sh uninstall
./dev.sh install --prod
```

This preserves database and credential files; migrate an existing database as
described in [operations](../guides/operations.md) before restarting. Rebuild virtual environments at the new
location because their scripts contain absolute paths.

</details>

Use an editable install for work on the service, SDK, or MCP adapter:

```sh
mise run setup
mise run test
```

For locked development, keep the `../aixand-libraries/filesystem` checkout and use:

```sh
./dev.sh develop
./dev.sh check
./dev.sh test
```

The tests cover authentication, inbox isolation, delivery semantics, persistence,
the SDK, and real stdio MCP exchanges. Use `./dev.sh reinstall` (or
`.\dev.ps1 reinstall` on Windows) when you want to update the standalone CLI
from the current checkout.

