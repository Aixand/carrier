"""Check Python, CLI, product, and tag versions without importing Carrier."""

import ast
import os
from pathlib import Path
import tomllib

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]


def main():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    product = tomllib.loads((ROOT / "installation.toml").read_text())
    module = ast.parse((ROOT / "carrier/__init__.py").read_text())
    cli_version = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
    )
    version = project["version"]
    versions = [
        cli_version,
        product["workspace"]["version"],
        product["products"]["carrier"]["version"],
    ]
    if any(Version(item) != Version(version) for item in versions):
        raise SystemExit(
            "Python package, CLI, workspace, and product versions must agree."
        )
    tag = os.environ.get("RELEASE_TAG", "")
    if tag and tag != f"v{version}":
        raise SystemExit(f"Release tag {tag!r} must be v{version}.")
    print(f"Version check passed: {project['name']} {version}")


if __name__ == "__main__":
    main()
