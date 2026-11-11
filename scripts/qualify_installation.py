"""Qualify a real Carrier artifact through a copied consumer, outside the checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def build_upgrade(base):
    """Build an actual next-version wheel in disposable sources, without editing ROOT."""
    source = base / "upgrade-source/carrier"
    ignored = shutil.ignore_patterns(
        ".git",
        ".venv",
        "build",
        "dist",
        "__pycache__",
        "*.pyc",
        "*.egg-info",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "AGENTS.md",
        ".carrier",
        "*.db",
        "*.db-wal",
        "*.db-shm",
    )
    shutil.copytree(ROOT, source, ignore=ignored)
    shutil.copytree(
        ROOT.parent / "aixand-libraries/filesystem",
        source.parent / "aixand-libraries/filesystem",
        ignore=ignored,
    )
    shutil.copytree(ROOT / "build/runtimes", source / "build/runtimes")
    configuration = tomllib.loads((source / "installation.toml").read_text())
    current = configuration["products"]["carrier"]["version"]
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", current)
    if not match:
        raise RuntimeError(f"Cannot create a qualification version from {current!r}")
    version = f"{match[1]}.{match[2]}.{int(match[3]) + 1}"

    # An upgrade must change the immutable product identity as well as its wheel.
    for name, sections in (
        ("pyproject.toml", {"project"}),
        ("installation.toml", {"workspace", "products.carrier"}),
    ):
        manifest = source / name
        lines = manifest.read_text().splitlines(keepends=True)
        section = None
        updated = set()
        for index, line in enumerate(lines):
            if line.startswith("["):
                section = line.strip().strip("[]")
            if section in sections and line.startswith("version = "):
                lines[index] = f'version = "{version}"\n'
                updated.add(section)
        if updated != sections:
            raise RuntimeError(f"Missing qualification version fields in {name}")
        manifest.write_text("".join(lines))
    module = source / "carrier/__init__.py"
    module.write_text(
        re.sub(
            r'^__version__ = "[^"]+"$',
            f'__version__ = "{version}"',
            module.read_text(),
            flags=re.MULTILINE,
        )
    )
    # Only the root version changes; preserve the resolved dependency graph.
    # Re-resolving would require optional integration sources outside this copy.
    lock = source / "uv.lock"
    locked, count = re.subn(
        r'(\[\[package\]\]\nname = "aixand-carrier-mcp"\nversion = ")[^"]+("\n)',
        lambda match: match[1] + version + match[2],
        lock.read_text(),
    )
    if count != 1:
        raise RuntimeError("Expected one Carrier package in the qualification lock")
    lock.write_text(locked)
    artifact = base / "upgrade-artifact"
    subprocess.run(
        [
            sys.executable,
            "-B",
            str(source / "scripts/dev/cli.py"),
            "--project",
            str(source),
            "package",
            "--output",
            str(artifact),
        ],
        cwd=source,
        check=True,
        stdout=sys.stderr,
    )
    return artifact


def qualify(artifact, output, upgrade=None, build_next=False, bootstrap=None):
    artifact = artifact.resolve()
    with tempfile.TemporaryDirectory(prefix="carrier installation 世界 ") as temporary:
        base = Path(temporary)
        if build_next:
            upgrade = build_upgrade(base)
        helper = base / "helper"
        shutil.copytree(
            ROOT / "scripts/dev",
            helper,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        env = {
            **os.environ,
            "PATH": ""
            if os.name != "nt"
            else str(Path(os.environ["SystemRoot"]) / "System32"),
            "PIP_NO_INDEX": "1",
            "UV_OFFLINE": "1",
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "NO_PROXY": "127.0.0.1,localhost",
        }
        # -I ignores injected Python configuration in the consumer and payload probes.
        env.update(
            PYTHONPATH=str(base / "missing-source"),
            PYTHONHOME=str(base / "missing-python"),
        )

        # Only the first-stage bootstrap downloads its pinned helper interpreter.
        # Product installation below has blocked proxies and no language tools in PATH.
        bootstrap_tested = False
        if bootstrap:
            bootstrap = bootstrap.resolve()
            bootstrap_env = {
                **os.environ,
                "AIXAND_INSTALLER_CACHE": str(base / "bootstrap-cache"),
                "PIP_NO_INDEX": "1",
                "UV_OFFLINE": "1",
            }
            if os.name == "nt":
                command = [
                    shutil.which("pwsh") or shutil.which("powershell"),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(bootstrap / "bootstrap.ps1"),
                ]
                bootstrap_env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
            else:
                tools = base / "bootstrap-tools"
                tools.mkdir()
                for name in (
                    "sh",
                    "curl",
                    "tar",
                    "gzip",
                    "sha256sum",
                    "shasum",
                    "uname",
                    "mkdir",
                    "mktemp",
                    "mv",
                    "rm",
                    "rmdir",
                ):
                    executable = shutil.which(name)
                    if executable:
                        (tools / name).symlink_to(executable)
                bootstrap_env["PATH"] = str(tools)
                command = ["/bin/sh", str(bootstrap / "bootstrap.sh")]
            subprocess.run(
                [
                    *command,
                    "install",
                    "--artifact",
                    str(artifact),
                    "--prefix",
                    str(base / "bootstrap-store"),
                ],
                cwd=base,
                env=bootstrap_env,
                check=True,
                stdout=sys.stderr,
                timeout=240,
            )
            subprocess.run(
                [
                    *command,
                    "exec",
                    "--prefix",
                    str(base / "bootstrap-store"),
                    "--command",
                    "carrier",
                    "--",
                    "--help",
                ],
                cwd=base,
                env=bootstrap_env,
                check=True,
                stdout=sys.stderr,
                timeout=60,
            )
            bootstrap_tested = True

        def run(*args, ok=True):
            result = subprocess.run(
                [str(v) for v in args],
                cwd=base,
                env=env,
                text=True,
                capture_output=True,
                timeout=180,
            )
            if ok != (result.returncode == 0):
                raise RuntimeError(
                    f"Unexpected result ({result.returncode}): {args}\n{result.stdout}\n{result.stderr}"
                )
            return result

        def consumer(operation, *args, ok=True):
            result = run(
                sys.executable,
                "-I",
                "-B",
                helper / "consumer.py",
                operation,
                *args,
                ok=ok,
            )
            if not ok:
                return result
            if "--events" in args:
                return json.loads(result.stdout.splitlines()[-1])["result"]
            return json.loads(result.stdout)

        def entry(store):
            consumer("inspect", "--prefix", store)
            return json.loads((store / "installation-receipt.json").read_text())[
                "products"
            ]["carrier"]

        def smoke(store, state):
            installed = entry(store)
            return json.loads(
                run(
                    installed["python"],
                    "-I",
                    "-B",
                    store / installed["payload"] / "share/carrier/verify.py",
                    "--state-root",
                    state,
                ).stdout
            )

        shared, private = base / "shared tools", base / "suite runtime"
        for store, scope, owner in (
            (shared, "shared", "user"),
            (private, "private", "aixand-suite"),
        ):
            consumer(
                "install",
                "--artifact",
                artifact,
                "--prefix",
                store,
                "--scope",
                scope,
                "--owner",
                owner,
                "--request-id",
                f"{scope}-setup",
                "--events",
                "jsonl",
            )
            consumer(
                "install",
                "--artifact",
                artifact,
                "--prefix",
                store,
                "--scope",
                scope,
                "--owner",
                owner,
                "--request-id",
                f"{scope}-setup",
                "--events",
                "jsonl",
            )
            command = store / "bin" / ("carrier.exe" if os.name == "nt" else "carrier")
            run(command, "--help")
            # Shared commands must use an owned runtime, even if setup was run by
            # a temporary developer interpreter or Suite's installation UI.
            shim = (
                store
                / "bin"
                / ("carrier.aixand-command" if os.name == "nt" else "carrier")
            )
            descriptor = shim.read_text(encoding="utf-8")
            if os.name == "nt":
                fields = descriptor.splitlines()
                assert fields[0] == "aixand-command/2" and len(fields) == 5
                assert (
                    Path(fields[1])
                    .resolve()
                    .is_relative_to((store / "runtimes").resolve())
                )
            else:
                assert str(store / "runtimes") in descriptor
            smoke(store, store / "data")
        consumer(
            "install",
            "--artifact",
            artifact,
            "--prefix",
            private,
            "--scope",
            "private",
            "--owner",
            "another-app",
            ok=False,
        )
        before = entry(shared)
        data = shared / "data"
        credentials = {p.name: p.read_bytes() for p in data.glob("*.json")}
        consumer("reinstall", "--artifact", artifact, "--prefix", shared)
        assert entry(shared)["payload"] != before["payload"]
        smoke(shared, data)
        assert {p.name: p.read_bytes() for p in data.glob("*.json")} == credentials
        consumer("rollback", "--prefix", shared, "--product", "carrier", ok=False)
        # A truncated copy must fail before it can replace the working selection.
        corrupt = base / "corrupt"
        shutil.copytree(artifact, corrupt)
        manifest = json.loads((corrupt / "release-manifest.json").read_text())
        victim = corrupt / next(iter(manifest["files"]))
        victim.write_bytes(b"damaged artifact")
        prior = entry(shared)["payload"]
        consumer("upgrade", "--artifact", corrupt, "--prefix", shared, ok=False)
        assert entry(shared)["payload"] == prior
        upgraded = False
        if upgrade:
            consumer("upgrade", "--artifact", upgrade.resolve(), "--prefix", shared)
            assert entry(shared)["product"]["version"] != before["product"]["version"]
            smoke(shared, data)
            assert {p.name: p.read_bytes() for p in data.glob("*.json")} == credentials
            upgraded = True
        # Removing Suite's private copy must leave the shared product usable.
        consumer("uninstall", "--prefix", private, "--product", "carrier", ok=False)
        consumer("uninstall", "--prefix", private, "--product", "carrier", "--stopped")
        assert (private / "data/carrier.db").is_file()
        smoke(shared, data)
        consumer("uninstall", "--prefix", shared, "--product", "carrier", "--stopped")
        assert not consumer("inspect", "--prefix", shared)["products"]
        assert (data / "carrier.db").is_file()
        assert {p.name: p.read_bytes() for p in data.glob("*.json")} == credentials
        result = {
            "verified": True,
            "target": manifest["target"],
            "manifest_sha256": hashlib.sha256(
                (artifact / "release-manifest.json").read_bytes()
            ).hexdigest(),
            "shared_and_private": True,
            "empty_tool_path": True,
            "bootstrap_without_system_python": bootstrap_tested,
            "offline_install": True,
            "service_and_sdk": True,
            "resume": True,
            "reinstall": True,
            "corrupt_upgrade_rejected": True,
            "upgrade_tested": upgraded,
            "stateful_rollback_rejected": True,
            "stopped_uninstall": True,
            "data_preserved": True,
        }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--upgrade-artifact", type=Path)
    parser.add_argument("--build-upgrade", action="store_true")
    parser.add_argument("--bootstrap", type=Path)
    args = parser.parse_args()
    if args.build_upgrade and args.upgrade_artifact:
        parser.error("Choose --build-upgrade or --upgrade-artifact")
    qualify(
        args.artifact,
        args.report,
        args.upgrade_artifact,
        args.build_upgrade,
        args.bootstrap,
    )
