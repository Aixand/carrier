# Publish Carrier to PyPI

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
separate [installer qualification procedure](installer-validation.md).
