"""Assemble only locked third-party wheels and Carrier's portable launch/check files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.parse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/dev"))
from catalog import host
from core import digest
from runtime_support import download
from prepare_runtime import prepare


def run(*argv, capture=False):
    return subprocess.run(
        [str(v) for v in argv],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else sys.stderr,
    ).stdout


def build(output, target):
    if target != host():
        raise RuntimeError(
            "Carrier wheelhouses must be built and tested on their native target"
        )
    prepare(target)
    wheelhouse = output / "wheelhouse"
    wheelhouse.mkdir(parents=True)
    share = output / "share/carrier"
    share.mkdir(parents=True)
    # uv selects environment markers; every selected index package must match uv.lock.
    export = run(
        "uv",
        "export",
        "--frozen",
        "--no-dev",
        "--no-emit-project",
        "--no-emit-package",
        "aixand-lib-filesystem",
        "--format",
        "requirements.txt",
        "--no-hashes",
        "--no-header",
        "--no-annotate",
        capture=True,
    )
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    packages = {(p["name"], p["version"]): p for p in lock["package"]}
    # Evaluate markers and tags with the pinned interpreter and locked build tools.
    # uv environments do not bundle pip, and pip's private modules are not an API.
    native = json.loads(
        run(
            "uv",
            "run",
            "--frozen",
            "--python",
            "3.12.14",
            "python",
            "-I",
            "-c",
            "import json,sys; from packaging.tags import sys_tags; "
            "from packaging.requirements import Requirement; "
            "requirements=[Requirement(v) for v in sys.argv[1].splitlines() if v.strip() and not v.startswith('#')]; "
            "print(json.dumps({'tags':list(map(str,sys_tags())), 'selected':[str(v).split(';')[0].strip() for v in requirements if v.marker is None or v.marker.evaluate()]}))",
            export,
            capture=True,
        )
    )
    tags, selected = native["tags"], native["selected"]
    ranking = {tag: i for i, tag in enumerate(tags)}
    inventory = []
    for spec in selected:
        if not spec.strip() or spec.startswith("#"):
            continue
        name, version = spec.split("==")
        package = packages[name, version]
        choices = []
        for wheel in package.get("wheels", []):
            filename = urllib.parse.unquote(
                urllib.parse.urlsplit(wheel["url"]).path.rsplit("/", 1)[-1]
            )
            python, abi, platform = filename[:-4].rsplit("-", 3)[-3:]
            score = min(
                (
                    ranking.get(f"{p}-{a}-{s}", 10**9)
                    for p in python.split(".")
                    for a in abi.split(".")
                    for s in platform.split(".")
                ),
                default=10**9,
            )
            if score < 10**9:
                choices.append((score, filename, wheel))
        if not choices and name == "cryptography" and target == "macos-x86_64":
            # Upstream no longer ships Intel macOS wheels. Build only this explicit
            # exception from its checksum-verified locked source, never downgrade.
            source = package["sdist"]
            with tempfile.TemporaryDirectory(prefix="carrier-cryptography-") as temp:
                archive = Path(temp) / "cryptography.tar.gz"
                download(source["url"], archive, source["hash"].removeprefix("sha256:"))
                built = Path(temp) / "wheels"
                run(
                    "uv",
                    "build",
                    "--no-sources",
                    "--wheel",
                    "--python",
                    "3.12.14",
                    "--out-dir",
                    built,
                    archive,
                )
                wheels = list(built.glob("cryptography-*.whl"))
                if len(wheels) != 1 or not wheels[0].name.startswith(
                    f"cryptography-{version}-"
                ):
                    raise RuntimeError("Unexpected cryptography source build output")
                filename = wheels[0].name
                path = wheelhouse / filename
                shutil.copyfile(wheels[0], path)
            wheel = source
        else:
            if not choices:
                raise RuntimeError(f"No locked native wheel for {spec} on {target}")
            _, filename, wheel = min(choices, key=lambda x: (x[0], x[1]))
            path = wheelhouse / filename
            download(wheel["url"], path, wheel["hash"].removeprefix("sha256:"))
        inventory.append(
            {
                "name": name,
                "version": version,
                "filename": filename,
                "sha256": digest(path),
                "source": wheel["url"],
            }
        )
    (share / "dependencies.json").write_text(json.dumps(inventory, indent=2) + "\n")
    (share / "requirements.txt").write_text(export, encoding="utf-8")
    shutil.copyfile(ROOT / "uv.lock", share / "uv.lock")
    shutil.copyfile(ROOT / "scripts/verify_product.py", share / "verify.py")
    (share / "launch.py").write_text("from carrier.cli import main\nmain()\n")
    # Preserve original bytes and provenance without reproducing arbitrarily
    # deep wheel paths underneath Windows build/install directories.
    notice_index = {}
    for wheel in wheelhouse.glob("*.whl"):
        notice_files = {}
        with zipfile.ZipFile(wheel) as archive:
            for entry in archive.namelist():
                if entry.endswith("/"):
                    continue
                if ".dist-info/" in entry and (
                    entry.endswith("/METADATA")
                    or any(v in entry.lower() for v in ("license", "notice", "copying"))
                ):
                    content = archive.read(entry)
                    logical = (
                        "share/notices/dependencies/"
                        + hashlib.sha256(content).hexdigest()
                        + ".txt"
                    )
                    destination = output / logical
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
                    notice_files[entry] = logical
        notice_index[wheel.name] = notice_files
    (output / "share/notices/dependencies/index.json").write_text(
        json.dumps(notice_index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    build(args.output.resolve(), args.target)
