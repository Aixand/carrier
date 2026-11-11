"""Prepare immutable native Carrier downloads from qualified product handoffs."""

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
import tarfile
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[2]
TARGETS = (
    "linux-x86_64-gnu",
    "linux-arm64-gnu",
    "macos-x86_64",
    "macos-arm64",
    "windows-x86_64-msvc",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def git(*args, root=ROOT):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def check(version, libraries_ref, root=ROOT):
    require(
        re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?", version),
        "Expected a product SemVer",
    )
    require(
        re.fullmatch(r"[a-f0-9]{40}", libraries_ref),
        "Pin libraries to a full commit SHA",
    )
    config = tomllib.loads((root / "installation.toml").read_text())
    require(
        config["workspace"]["version"]
        == config["products"]["carrier"]["version"]
        == version,
        "Product versions differ",
    )
    # This also checks the normalized Python and CLI versions; native tags use
    # product SemVer, while the separate PyPI workflow uses Python versions.
    env = os.environ.copy()
    env.pop("RELEASE_TAG", None)
    subprocess.run(
        [sys.executable, str(root / "scripts/checks/check-release-version.py")],
        env=env,
        check=True,
    )
    require(
        not git("status", "--porcelain", "--untracked-files=normal", root=root),
        "Carrier release sources must be clean",
    )
    libraries = root.parent / "aixand-libraries"
    require(
        git("rev-parse", "HEAD", root=libraries) == libraries_ref,
        "Libraries checkout differs from pinned commit",
    )
    require(
        not git("status", "--porcelain", "--untracked-files=normal", root=libraries),
        "Library release sources must be clean",
    )
    return git("rev-parse", "HEAD", root=root)


def evidence(
    manifest_bytes, descriptor, proof, lifecycle, version, commit, libraries_ref, target
):
    manifest = json.loads(manifest_bytes)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    require(
        manifest["schema"] == descriptor["schema"] == proof["schema"] == 2,
        "Wrong handoff schema",
    )
    require(
        manifest["version"] == descriptor["version"] == version,
        "Handoff version differs",
    )
    require(
        manifest["selection"] == descriptor["selection"] == "carrier",
        "Not a Carrier selection",
    )
    require(
        all(
            row["target"] == target for row in (manifest, descriptor, proof, lifecycle)
        ),
        "Handoff target differs",
    )
    require(
        all(row["manifest_sha256"] == digest for row in (descriptor, proof, lifecycle)),
        "Evidence is not bound to these bytes",
    )
    require(
        proof["kind"] == "installation-verification"
        and proof["verified"] is True
        and proof["installation_tested"] is True,
        "Missing native installation verification",
    )
    require(
        descriptor["verification"]["runtime"] is True,
        "Missing exported runtime verification",
    )
    require(
        lifecycle["verified"] is True
        and lifecycle["upgrade_tested"] is True
        and lifecycle["bootstrap_without_system_python"] is True,
        "Missing lifecycle, upgrade, or bootstrap qualification",
    )
    require(
        set(manifest["products"]) == set(descriptor["products"]) == {"carrier"},
        "Unexpected products",
    )
    product = manifest["products"]["carrier"]
    require(
        product["version"] == version and set(product["commands"]) == {"carrier"},
        "Unexpected product version or commands",
    )
    require(
        descriptor["products"]["carrier"]["release"] == product["release"],
        "Product release identity differs",
    )
    sources = manifest["sources"]
    require(set(sources) == {"project", "filesystem"}, "Unexpected source inventory")
    for name, expected in (("project", commit), ("filesystem", libraries_ref)):
        require(
            sources[name]["commit"] == expected and sources[name]["dirty"] is False,
            "Artifact was built from different or dirty sources",
        )
    return manifest


def archive(version, libraries_ref, root=ROOT):
    commit = check(version, libraries_ref, root)
    sys.path.insert(0, str(root / "scripts/dev"))
    from releases import validate

    handoff = root / "dist/handoff"
    artifacts, manifest = validate(handoff / "artifacts")
    target = manifest["target"]
    require(target in TARGETS, "Unknown native target")
    evidence(
        (artifacts / "release-manifest.json").read_bytes(),
        read(handoff / "product-descriptor.json"),
        read(handoff / "verification-report.json"),
        read(root / "dist/lifecycle.json"),
        version,
        commit,
        libraries_ref,
        target,
    )
    name = f"carrier-{version}-{target}"
    output = root / "dist/assets"
    output.mkdir(exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="carrier-download-") as temporary:
        stage = Path(temporary) / name
        shutil.copytree(handoff, stage)
        shutil.copytree(root / "dist/bootstrap", stage / "bootstrap")
        bootstrap = (
            stage
            / "bootstrap"
            / ("bootstrap.ps1" if target.startswith("windows") else "bootstrap.sh")
        )
        require(bootstrap.is_file(), "Missing native bootstrap")
        shutil.copyfile(root / "dist/lifecycle.json", stage / "lifecycle.json")
        (stage / "release-metadata.json").write_text(
            json.dumps(
                dict(
                    version=version,
                    tag=f"v{version}",
                    target=target,
                    commit=commit,
                    libraries_commit=libraries_ref,
                ),
                indent=2,
            )
            + "\n"
        )
        (stage / "INSTALL.txt").write_text(
            "Carrier installation\n\nKeep this directory together. Use bootstrap/bootstrap.sh or bootstrap/bootstrap.ps1\nwith plan/install --artifact /absolute/path/to/artifacts --prefix /absolute/store.\nSetup downloads a pinned helper interpreter. Carrier includes its own runtime.\nInstallation starts no service. Start it explicitly with carrier serve.\nDatabases and credentials are separate from software.\nDocumentation: https://github.com/Aixand/carrier/blob/v"
            + version
            + "/docs/installation.md\n"
        )
        require(
            not any(path.is_symlink() for path in stage.rglob("*")),
            "Release downloads must not contain links",
        )
        fmt = "zip" if target.startswith("windows") else "gztar"
        result = shutil.make_archive(str(output / name), fmt, temporary, name)
        print(result)


def collect(version, libraries_ref, commit, assets):
    require(re.fullmatch(r"[a-f0-9]{40}", commit), "Expected a source commit SHA")
    expected = {
        f"carrier-{version}-{target}."
        + ("zip" if target.startswith("windows") else "tar.gz"): target
        for target in TARGETS
    }
    files = list(assets.iterdir())
    require(
        {p.name for p in files} == set(expected)
        and all(p.is_file() and not p.is_symlink() for p in files),
        "Native archive set is incomplete or unexpected",
    )
    for path in files:
        target = expected[path.name]
        base = f"carrier-{version}-{target}/"
        if path.suffix == ".zip":
            stream = zipfile.ZipFile(path)

            def entry(name):
                info = stream.getinfo(base + name)
                require(info.file_size <= 8 * 1024 * 1024, "Oversized release metadata")
                return stream.read(info)
        else:
            stream = tarfile.open(path, "r:gz")

            def entry(name):
                info = stream.getmember(base + name)
                require(
                    info.isfile() and info.size <= 8 * 1024 * 1024,
                    "Invalid release metadata",
                )
                return stream.extractfile(info).read()

        with stream:
            evidence(
                entry("artifacts/release-manifest.json"),
                json.loads(entry("product-descriptor.json")),
                json.loads(entry("verification-report.json")),
                json.loads(entry("lifecycle.json")),
                version,
                commit,
                libraries_ref,
                target,
            )
            metadata = json.loads(entry("release-metadata.json"))
            require(
                metadata
                == dict(
                    version=version,
                    tag=f"v{version}",
                    target=target,
                    commit=commit,
                    libraries_commit=libraries_ref,
                ),
                "Release metadata differs",
            )
    (assets / "SHA256SUMS").write_text(
        "".join(f"{sha(p)}  {p.name}\n" for p in sorted(files)), encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "archive", "collect"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--libraries-ref", required=True)
    parser.add_argument("--commit")
    parser.add_argument("--assets", type=Path, default=ROOT / "dist/assets")
    args = parser.parse_args()
    if args.operation == "collect":
        require(args.commit is not None, "Collection needs --commit")
        collect(args.version, args.libraries_ref, args.commit, args.assets)
    elif args.operation == "archive":
        archive(args.version, args.libraries_ref)
    else:
        check(args.version, args.libraries_ref)


if __name__ == "__main__":
    main()
