# Develop and validate Carrier locally

Use this guide to prepare the locked development environment and verify a change.
Run commands from the Carrier repository root. Shell examples use Bash on
Linux/macOS; Windows uses `.\dev.ps1` for the same developer operations.

## Prepare the environment

Keep `carrier` and `aixand-libraries` as sibling source checkouts, as described in
[source prerequisites](installation.md#source-checkout-prerequisites).
Install Python 3.11+ and uv 0.12.7 before running the helper:

```sh
./dev.sh doctor
./dev.sh develop
./dev.sh check
./dev.sh test
```

`develop` selects CPython 3.12.14 and creates `.venv` with locked development
dependencies. `doctor` reports helper/tool availability; it does not qualify a
native product or prove a successful install. `check` validates Ruff lint and
the selected adapter formatting, documentation, and the Git index file policy.
`test` runs the service/SDK/MCP/installer tests and the documentation and repository policy checker regression suites.
Successful operations exit zero. Review skip reasons when assessing platform coverage.

The product helper consumes `uv.lock` with `--frozen`, without resolving unused
optional integration sources. Regenerate and review the lock intentionally in the
full development workspace when dependency metadata changes.

Install or integrate the repository policy hook in each clone:

```sh
python3 scripts/checks/install-file-policy-hook.py
```

See [the file policy](../REPOSITORY_FILES.md) for existing hook managers and history
checks. Local hooks do not enable repository protections.

## Find the implementation

| Responsibility | Owning source |
| --- | --- |
| HTTP service, authentication, persistence | [service.py](../carrier/service.py) |
| Command arguments and defaults | [cli.py](../carrier/cli.py) |
| Async messaging and consumer behavior | [sdk.py](../carrier/sdk.py) · [models.py](../carrier/models.py) · [errors.py](../carrier/errors.py) |
| Local identity provisioning | [provision.py](../carrier/provision.py) |
| MCP tools | [adapter.py](../carrier/adapter.py) |
| Source/product installer routing | [carrier_dev.py](../scripts/carrier_dev.py) |
| Product components, commands, and runtime pins | [installation.toml](../installation.toml) |

The copied `scripts/dev/` helpers follow installation-template revision 2.
Keep Carrier-specific routing and payload logic outside those shared helpers.
Review copied template updates explicitly and preserve the legacy installer's
receipt ownership. Databases and credentials belong outside versioned software.

## Run focused checks

For a service or SDK change, run the relevant tests before the complete suite:

```sh
uv run --locked python -m pytest -q tests/test_carrier.py tests/test_sdk.py
```

For source/product routing or replacement behavior:

```sh
uv run --locked python -m pytest -q tests/test_installer_routing.py tests/test_dev_installer.py
```

The [SDK guide](python-sdk.md#runnable-examples) provides application-level
workflows. Keep example databases separate from normal operation. Stop example
services with Ctrl+C; retain their credentials to repeat runs against the same database.

## Check documentation

The Markdown checker and its regression tests use only Python's standard library:

```sh
python3 scripts/checks/check-docs.py --root .
python3 tests/tooling/checks/docs_test.py
```

The checker covers the root Markdown pages and `docs/`. It checks local links,
anchors, headings, code fences, template tokens, and diagram accessibility fields.
External URLs and command behavior require separate checks.

Changed Mermaid diagrams also need rendering and visual inspection. With Node.js
22.13+ and npm available, install the locked optional tools:

```sh
npm ci --prefix tools/docs
python3 scripts/checks/check-docs.py --root . --render-mermaid build/docs-diagrams \
  --mmdc tools/docs/node_modules/.bin/mmdc
```

Use a new preview directory on each run. Inspect the generated default and dark
images for readable labels, complete arrows, contrast, and clipping. If an existing
Chromium installation is required, pass `--puppeteer-config` with its local launch
configuration. Keep local browser configuration and previews under ignored `build/`.
Preview in the publishing renderer before publication; a local render verifies
the bundled renderer only.

## Verify an installed distribution

Use an unused temporary virtual environment outside the source checkout. The
following Bash example builds the current Python distribution and installs it
with the published filesystem dependency. Network access is required for build and
third-party dependencies:

```sh
uv build --no-sources --wheel --sdist --out-dir dist/python
python3 -m venv /absolute/path/carrier-smoke
/absolute/path/carrier-smoke/bin/python -m pip install dist/python/aixand_carrier_mcp-*.whl
/absolute/path/carrier-smoke/bin/python -I scripts/verify_product.py
```

Replace `/absolute/path/carrier-smoke` with a new disposable location. Use a fresh
`dist/python` directory so the wheel glob selects only the intended version.
The verifier checks installed imports, credential reuse, and a loopback HTTP
send/retry/reply/acknowledge exchange. Success prints `verified: true` in JSON.
It stops its temporary service and removes temporary state when finished.
Remove the disposable environment after inspection.

For a native bundled product, use the full [package and lifecycle qualification](installation.md#build-and-verify)
instead. A Python wheel smoke test does not establish bundled runtime or native
platform support.

## Continuous integration

The repository runs these workflows on pull requests and pushes to `main`:

| Workflow | Coverage |
| --- | --- |
| [Documentation](../.github/workflows/docs.yml) | Markdown validation and checker regression tests |
| [Repository files](../.github/workflows/repository-files.yml) | Tracked paths, introduced commits, and policy regression tests |
| [Secret scanning](../.github/workflows/secret-scan.yml) | Fetched Git history with checksum-pinned Gitleaks and redacted output |
| [Python package](../.github/workflows/publish.yml) | Wheel/sdist build, public dependency installation, service/SDK tests, and PyPI publication on version tags |
| [Product installer](../.github/workflows/installer.yml) | Native setup, lint, tests, packaging, installation, and lifecycle qualification |

The first three workflows run independently of the paired library checkout.
The installer workflow requires the repository variables described in
[native release qualification](installer-validation.md#qualify-native-releases).
Workflow files do not prove a successful remote run or configure required checks.
Review the GitHub results for the exact commit before publishing.

Ignore rules reduce accidental additions of local secrets and generated files.
They do not remove tracked files or secrets already present in Git history.

See [PyPI releases](releases.md) for Trusted Publisher setup and tag version rules.
