"""Preserve Carrier's source installer while exposing revision-2 product commands."""

import os
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def legacy(arguments):
    if not arguments:
        return False
    action = arguments[0]
    # A bare reinstall/uninstall belongs to the original installer's receipts.
    return (action == "install" and "--prod" in arguments) or (
        action in {"reinstall", "uninstall"}
        and not any(
            any(arg == flag or arg.startswith(flag + "=") for arg in arguments)
            for flag in (
                "--artifact",
                "--prefix",
                "--product",
                "--scope",
                "--owner",
                "--register-path",
                "--command-policy",
            )
        )
    )


def source_error(arguments):
    """Check paired sources before a source operation can create install state."""
    if not arguments:
        return None
    operation = arguments[0]
    artifact = any(
        arg == "--artifact" or arg.startswith("--artifact=") for arg in arguments
    )
    required = operation in {
        "doctor",
        "develop",
        "check",
        "test",
        "build",
        "package",
        "release-check",
    } or (operation in {"install", "reinstall"} and not artifact)
    if not required:
        return None
    manifest = ROOT.parent / "aixand-libraries/filesystem/pyproject.toml"
    try:
        metadata = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (
            f"Missing or invalid aixand-lib-filesystem source: {manifest}. "
            "Place aixand-libraries/filesystem alongside the Carrier checkout. "
            "See docs/installation.md#source-checkout-prerequisites."
        )
    if metadata.get("project", {}).get("name") != "aixand-lib-filesystem":
        return f"Expected the aixand-lib-filesystem distribution in {manifest}."
    return None


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    error = source_error(arguments)
    if error:
        print(f"Carrier setup: {error}", file=sys.stderr)
        return 2
    if legacy(arguments):
        script = ROOT / "scripts/dev.py"
        # The original source route now assembles its local first-party wheel too.
        argv = [sys.executable, "-B", str(script), *arguments]
    else:
        if not arguments or arguments[0] in {"help", "-h", "--help"}:
            print(
                "Carrier: install --prod, bare reinstall/uninstall manage legacy source "
                "installations. Product operations use --artifact/--prefix/--product; "
                "see docs/installation.md.",
                file=sys.stderr,
            )
        argv = [
            sys.executable,
            "-B",
            str(ROOT / "scripts/dev/cli.py"),
            "--project",
            str(ROOT),
            *arguments,
        ]
    return subprocess.call(argv, env=os.environ.copy())


if __name__ == "__main__":
    raise SystemExit(main())
