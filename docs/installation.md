# Carrier product installation

Carrier uses installation-template revision 2. One native release contains the
service, `carrier` CLI, MCP adapter, Python SDK, `aixand-lib-filesystem` wheel,
locked third-party wheels, and checksum-pinned CPython 3.12.14. Build each target
on that target; the configured matrix is Linux GNU x64/ARM64, macOS Intel/ARM64,
and Windows x64. Declared targets become supported releases only after native
qualification. See [installer validation](installer-validation.md).

This guide describes local source builds and supplied artifacts on the development
branch. The [native release workflow](releases.md#publish-native-standalone-downloads)
prepares public archives; hosted endpoints require separate catalog registration.
For Python applications, `python -m pip install .` from the Carrier root resolves
the published filesystem dependency automatically. After Carrier is published,
use `python -m pip install aixand-carrier-mcp==0.1.0b0` in your application environment.
See [Python package releases](releases.md) for publication and verification.

The same payload has two installation scopes. Shared scope installs independent
commands in the user's product store. Private scope installs commands
inside an application's explicit store and records that application's owner.
Scope changes ownership and location; it does not change the packaged Carrier
service or imply that installing a CLI starts a service.

## Source checkout prerequisites

Obtain Carrier and `aixand-lib-filesystem` from the same source workspace. Both are
required sources for local development, source installation, and packaging:

```text
workspace/
  carrier/pyproject.toml
  aixand-libraries/filesystem/pyproject.toml
```

Run commands from `workspace/carrier`. The filesystem manifest must name the
`aixand-lib-filesystem` distribution. Its local path is declared in
[pyproject.toml](../pyproject.toml), [the lockfile](../uv.lock), and
[installation.toml](../installation.toml). Carrier does not download or create
that source checkout automatically. A missing source is reported before source
installation modifies an installation directory.

For a standalone source CLI, run `./dev.sh install --prod` or
`.\dev.ps1 install --prod`. For the Python SDK, install Carrier into your
application's virtual environment as shown in [the SDK guide](python-sdk.md).
These source routes resolve third-party dependencies online.

## Build and verify

Keep the canonical `../aixand-libraries/filesystem` source checkout alongside Carrier.
Builders need Python 3.11+, uv 0.12.7, and build interpreter 3.12.14.
Windows packaging also needs Rust 1.98.0 and the MSVC linker for native shims.
Project checks and tests use the locked development environment:

```sh
./dev.sh develop
./dev.sh check
./dev.sh test
./dev.sh package --output dist/release
./dev.sh verify --artifact dist/release --install --report dist/verification.json
python3 scripts/prepare_runtime.py --bootstrap-output dist/bootstrap
python3 scripts/qualify_installation.py dist/release --build-upgrade \
  --bootstrap dist/bootstrap --report dist/lifecycle.json
./dev.sh export-release --artifact dist/release \
  --report dist/verification.json --output dist/handoff
```

Each package output must be a new directory. If `dist/release` already exists,
select another output path and use it in the following commands. A successful
verification report has `verified: true` and `installation_tested: true`.
The checks use temporary identities and a loopback service, then stop that service.

PowerShell uses `.\dev.ps1` with the same arguments. Use `python` or `py -3`
for the Python script commands. Set `AIXAND_DEV_PYTHON` (or the existing
`CARRIER_DEV_PYTHON` override) to select the developer helper interpreter.

Packaging downloads the native runtime into ignored `build/runtimes/` and verifies
its pinned hash. Third-party wheel URLs and hashes come from `uv.lock`; native
Python evaluates environment markers and selects compatible wheel tags. The
builder rejects unavailable wheels, except for an explicit Intel macOS
cryptography build from its checksum-verified locked source with static OpenSSL.
First-party wheels are built from the two recorded sources with pinned backends.
The product receives the lock, selected dependency inventory, and notices carried
inside the wheels. The interpreter archive carries its upstream license files.

These interpreter pins come from the immutable
[python-build-standalone 20260825 release](https://github.com/astral-sh/python-build-standalone/releases/tag/20260825).
Update the runtime matrix and source URL mapping together, then rerun qualification.
The release records the build host's conservative OS/libc baseline; it does not
claim compatibility with older operating systems merely because Python runs there.

## Install the packaged product

After receiving an artifact and its matching bootstrap, a user can install without
Python, uv, Rust, an activated environment, or a source checkout:

```sh
sh /path/to/bootstrap/bootstrap.sh install \
  --artifact /path/to/release --product carrier
```

On Windows, invoke the supplied `bootstrap.ps1` through PowerShell 5.1+.
The first stage needs network access for its checksum-pinned helper interpreter.
Shell bootstrap also needs curl, tar/gzip, and a SHA-256 utility. The actual Carrier
payload includes its own interpreter and all runtime wheels, and installs offline.
Subsequent product commands use the store's interpreter rather than setup's Python.

For development, the checkout also exposes those artifact operations:

```sh
./dev.sh plan --artifact dist/release --prefix /absolute/path/shared-tools
./dev.sh install --artifact dist/release --prefix /absolute/path/shared-tools \
  --request-id carrier-setup --events jsonl
/absolute/path/shared-tools/bin/carrier --help
```

Default shared artifact stores:

| OS | Store |
| --- | --- |
| Linux | `$XDG_DATA_HOME/aixand/products`, default `~/.local/share/aixand/products` |
| macOS | `~/Library/Application Support/Aixand/products` |
| Windows | `%LOCALAPPDATA%\Aixand\products` |

Commands live in the store's `bin` directory, with native `.exe` launchers on
Windows. Add that directory to PATH explicitly if desired. Product installation
does not edit shell profiles or user PATH.

For a host application's private copy:

```sh
./dev.sh install --artifact dist/release --product carrier \
  --scope private --owner host-app \
  --prefix /absolute/path/host-app/runtime/products \
  --request-id host-app-carrier-setup --events jsonl
```

The host application calls its private command by absolute path and supplies its database,
service URL, and credential paths explicitly. An independent shared Carrier
installation stays usable after the host application's private Carrier copy is removed.

## Update, repair, and remove

Stop Carrier services and MCP adapters before replacing software they use.
Installation verifies a prepared selection before activating it and starts no
background service. Start the service explicitly with `carrier serve`.

```sh
./dev.sh upgrade --artifact /path/to/new-release --prefix /absolute/path/shared-tools
./dev.sh reinstall --artifact dist/release --prefix /absolute/path/shared-tools
./dev.sh inspect --prefix /absolute/path/shared-tools
./dev.sh uninstall --product carrier --prefix /absolute/path/shared-tools --stopped
```

Changed bytes require a new release version. Upgrade requires an explicit artifact,
and a damaged candidate leaves the working selection active. Reusing a request ID
resumes the same operation; incompatible request inputs are rejected.

Carrier is stateful: generic software rollback is rejected. There is no
automatic database rollback/migration adapter. Release owners must review database
compatibility and backup/migration requirements before shipping a changed schema.
Databases, credentials, and service configuration belong outside versioned payloads;
the default database remains `~/.aixand/carrier/carrier.db`. Uninstall removes owned
software and commands, preserving data and retained installer/runtime caches.

## Existing source installations and SDK consumers

`./dev.sh install --prod`, bare `reinstall`, and bare `uninstall` retain the original
source installer's paths and receipt format. They are separate from revision-2
product stores. PowerShell's automatic PATH update is retained only for that legacy
route. A product reinstall/uninstall must specify `--prefix` or `--product`.
The new installer does not silently adopt legacy installations.

The source route installs the sibling `aixand-lib-filesystem` package with Carrier.
It does not require a published copy of that dependency.
It still requires system Python and online dependency resolution. To install a new
source-owned revision-2 product, omit `--prod` and pass `--prefix`; its receipt keeps
source ownership separate from supplied-artifact ownership.

The SDK travels inside the CLI product's private environment for its own service,
MCP adapter, and checks. Other Python applications install `aixand-carrier-mcp` into their own environments;
pip resolves `aixand-lib-filesystem` automatically. The global CLI does not share its
environment with them.

## Publication handoff

`dist/handoff` contains a product descriptor, exact artifacts, and bound installation
verification. Keep the generated bootstrap and lifecycle report alongside it.
Export does not publish. Public catalog integration, hosting, and native release
qualification remain separate publication work.

Before an immutable release, source changes must be committed, dependency sources
pinned/reviewed, and the product tag `carrier/v<version>` checked with
`release-check`. Carrier uses [Apache-2.0](../LICENSE), declared in package metadata.
Python distributions include the license and [NOTICE](../NOTICE); native products
also carry first-party and dependency notices. Review all distributed components
and their notices before publishing an immutable release.
