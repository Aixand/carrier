# Publish Carrier releases

The [Python package workflow](../.github/workflows/publish.yml) builds and checks
`aixand-carrier-mcp` on pushes to `main`, pull requests, and manual runs. Pushing a `v*`
tag also publishes the checked wheel and source distribution to PyPI.
Creating a GitHub Release is not required.

## Configure publishing once

Create a GitHub environment named `pypi` in `Aixand/carrier`. Allow release tags
to deploy to it. Configure tag protection so only release maintainers can create
or change release tags.

Configure a [PyPI Trusted Publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
with these values. For a new project, use PyPI's pending publisher form.

| Field | Value |
| --- | --- |
| PyPI project | `aixand-carrier-mcp` |
| GitHub owner | `Aixand` |
| Repository | `carrier` |
| Workflow filename | `publish.yml` |
| Environment | `pypi` |

The publish job uses OpenID Connect with `id-token: write`. No PyPI API token is
needed. Only that job receives publishing permissions.

Publish a compatible `aixand-lib-filesystem` release before Carrier. The package check
installs from PyPI without sibling checkouts or uv source overrides. It fails if
a required dependency is unavailable. The optional `agent-manager` extra also
requires its dependency chain to be published before users can install that extra;
the base package check does not validate the optional integration.

## Prepare and push a release tag

Run commands from the Carrier repository root. Update the version in
`pyproject.toml`, `carrier/__init__.py`, and the workspace and Carrier product
sections of `installation.toml`. Python and product versions must normalize to
the same version. For example, Python `0.1.0b0` matches product `0.1.0-beta`.
Update `uv.lock` and record user-visible changes in the changelog.

Run local checks and inspect the complete change before committing it:

```sh
./dev.sh check
./dev.sh test
uv run --no-project --with packaging==26.3 python scripts/checks/check-release-version.py
```

Push the reviewed release commit to `main` and wait for its checks to pass.
The tag must be `v` followed by the exact version in `pyproject.toml`.
For package version `0.1.0b0`, run:

```sh
git tag v0.1.0b0
git push origin v0.1.0b0
```

Pushing this tag starts automatic publication after the build job succeeds and
any configured environment rules are satisfied. PyPI release files cannot be
replaced; use a new version to correct published artifacts.

## Verify the result

The build job validates versions, checks metadata with Twine, rebuilds a wheel
from the source distribution, and tests both installed builds. It also runs the
service and SDK tests. The installed verifier exercises a real loopback service
with disposable identities and removes its temporary state.

Check the workflow's publish result and the files on the
[Carrier PyPI project](https://pypi.org/project/aixand-carrier-mcp/). In a fresh environment,
install the exact published version and run `carrier --version` and `carrier --help`.
For this prerelease, the install command is:

```sh
python -m pip install aixand-carrier-mcp==0.1.0b0
carrier --version
carrier --help
```

If installation fails, inspect dependency availability and the build job's logs.
If publishing fails, check the Trusted Publisher's owner, repository, workflow,
and environment values. Rerun a failed job only after checking whether PyPI
already received any files.

This workflow publishes Python packages. Native standalone artifacts use the
separate workflow below.


## Publish native standalone downloads

The [Native release workflow](../.github/workflows/native-release.yml) builds
Carrier with a private CPython runtime and locked dependencies. Users do not need
system Python, uv, Rust, or a source checkout. It publishes GitHub downloads;
the hosted installer catalog is a separate registration and deployment step.

Run from a clean Carrier checkout after committing and pushing the release changes
to `main`. The `version` input must exactly match `installation.toml`. Pin
`libraries_ref` to a reviewed full commit SHA in `Aixand/aixand-libraries`.
Both Carrier and its dependency must be clean, committed inputs. Use a new version
for changed public bytes. Native tags use product SemVer, such as `v0.1.0-beta`;
PyPI tags use the Python package version, such as `v0.1.0b0`.

In GitHub Actions, select **Native release**, branch **main**, the exact version,
and the dependency commit. Leave **publish** unchecked for qualification only.
For a release, select **publish**; the release job still waits for all native
checks. The `release` GitHub environment can enforce repository approval rules.

The workflow qualifies Linux GNU x64/ARM64, macOS Intel/ARM64, and Windows x64.
Each native host runs repository checks, tests, actual product installation,
next-version upgrade, data preservation, and the Python-free bootstrap. It then
exports the handoff and creates the versioned archive. The collector requires all
five targets with matching source commits and evidence before generating
`SHA256SUMS`. A failed target prevents publication.

Downloads use these names, with `VERSION` and `TARGET` replaced by their exact
values:

- `carrier-VERSION-TARGET.tar.gz` on Linux and macOS.
- `carrier-VERSION-windows-x86_64-msvc.zip` on Windows.
- `SHA256SUMS` for the complete archive set.

Each archive includes its product objects, bootstrap, descriptor, installation
proof, lifecycle report, and release metadata. The `carrier` command launches the
packaged Python implementation; no separately compiled Carrier service is needed.
Windows still builds the product engine's native command launcher.

Publication creates a draft, uploads the checked files, then publishes it.
Existing releases are rejected rather than overwritten. If uploading fails,
inspect the retained draft and workflow artifacts. Do not replace published
files or rerun against an existing public version.

After publication, anonymously verify each actual download and register those
bytes with the hosted installer. Keep the same handoff and product identity for
Suite reuse. Native downloads do not add the SDK to another application's Python
environment; SDK consumers use the Python package route above.


## Qualify the hosted installer

After the public archives are registered as an exact version, keep the hosted
beta channel disabled while testing. Deploy that staged catalog, then run
[Qualify hosted installer](../.github/workflows/hosted-installer.yml) with the exact
registered version. The workflow reads the public catalog and versioned scripts;
it does not need access to the private installer repository.

The four hosted targets check confirmation and cancellation, archive hash
rejection, real shared/private stores, command versions, existing command
preservation, repeat setup, and uninstall preserving separate runtime data.
Checks use disposable homes and product stores. Windows skips user PATH changes.
The existing native lifecycle workflow separately verifies real messaging and
upgrade behavior. Enable the hosted beta channel only after these checks pass.
