"""Release metadata must bind native evidence to immutable inputs."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
import zipfile

import pytest

spec = importlib.util.spec_from_file_location(
    "carrier_native_release", Path(__file__).parents[1] / "scripts/release/native.py"
)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
VERSION = "0.1.0-beta"
COMMIT = "1" * 40
LIBRARIES = "2" * 40


def records(target):
    manifest = dict(
        schema=2,
        version=VERSION,
        selection="carrier",
        target=target,
        sources={
            "project": dict(commit=COMMIT, dirty=False),
            "filesystem": dict(commit=LIBRARIES, dirty=False),
        },
        products={
            "carrier": dict(
                version=VERSION,
                target=target,
                commands={"carrier": {}},
                release="3" * 64,
            )
        },
    )
    manifest_bytes = json.dumps(manifest).encode()
    bound = dict(
        target=target, manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest()
    )
    descriptor = dict(
        **bound,
        schema=2,
        version=VERSION,
        selection="carrier",
        verification=dict(runtime=True),
        products={"carrier": dict(release="3" * 64)},
    )
    proof = dict(
        **bound,
        schema=2,
        kind="installation-verification",
        verified=True,
        installation_tested=True,
    )
    lifecycle = dict(
        **bound,
        verified=True,
        upgrade_tested=True,
        bootstrap_without_system_python=True,
    )
    return manifest, descriptor, proof, lifecycle


def test_evidence_matches_native_inputs():
    manifest, descriptor, proof, lifecycle = records(native.TARGETS[0])
    assert (
        native.evidence(
            json.dumps(manifest).encode(),
            descriptor,
            proof,
            lifecycle,
            VERSION,
            COMMIT,
            LIBRARIES,
            native.TARGETS[0],
        )
        == manifest
    )


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "dirty",
        "dependency",
        "version",
        "commands",
        "target",
        "proof",
        "upgrade",
        "bootstrap",
        "release",
    ],
)
def test_rejects_mismatched_or_incomplete_evidence(change):
    manifest, descriptor, proof, lifecycle = copy.deepcopy(records(native.TARGETS[0]))
    if change == "source":
        manifest["sources"]["project"]["commit"] = "4" * 40
    elif change == "dirty":
        manifest["sources"]["project"]["dirty"] = True
    elif change == "dependency":
        manifest["sources"]["filesystem"]["commit"] = "4" * 40
    elif change == "version":
        manifest["products"]["carrier"]["version"] = "0.2.0"
    elif change == "commands":
        manifest["products"]["carrier"]["commands"]["foreign"] = {}
    elif change == "target":
        descriptor["target"] = "windows-x86_64-msvc"
    elif change == "proof":
        proof["installation_tested"] = False
    elif change == "upgrade":
        lifecycle["upgrade_tested"] = False
    elif change == "bootstrap":
        lifecycle["bootstrap_without_system_python"] = False
    else:
        descriptor["products"]["carrier"]["release"] = "4" * 64
    data = json.dumps(manifest).encode()
    # Rebind reports so these cases exercise semantic checks, not just hashing.
    for record in (descriptor, proof, lifecycle):
        record["manifest_sha256"] = hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError):
        native.evidence(
            data,
            descriptor,
            proof,
            lifecycle,
            VERSION,
            COMMIT,
            LIBRARIES,
            native.TARGETS[0],
        )


def archives(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    for target in native.TARGETS:
        manifest, descriptor, proof, lifecycle = records(target)
        stage = tmp_path / f"carrier-{VERSION}-{target}"
        (stage / "artifacts").mkdir(parents=True)
        (stage / "bootstrap").mkdir()
        (
            stage
            / "bootstrap"
            / ("bootstrap.ps1" if target.startswith("windows") else "bootstrap.sh")
        ).write_text("fixture bootstrap")
        for name, value in {
            "artifacts/release-manifest.json": manifest,
            "product-descriptor.json": descriptor,
            "verification-report.json": proof,
            "lifecycle.json": lifecycle,
            "release-metadata.json": dict(
                version=VERSION,
                tag=f"v{VERSION}",
                target=target,
                commit=COMMIT,
                libraries_commit=LIBRARIES,
            ),
        }.items():
            (stage / name).write_text(json.dumps(value))
        if target.startswith("windows"):
            with zipfile.ZipFile(assets / (stage.name + ".zip"), "w") as archive:
                for path in stage.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(tmp_path).as_posix())
        else:
            with tarfile.open(assets / (stage.name + ".tar.gz"), "w:gz") as archive:
                archive.add(stage, stage.name)
    return assets


def test_collect_binds_all_targets_and_checksums(tmp_path):
    assets = archives(tmp_path)
    native.collect(VERSION, LIBRARIES, COMMIT, assets)
    lines = (assets / "SHA256SUMS").read_text().splitlines()
    assert len(lines) == len(native.TARGETS)
    for line in lines:
        checksum, name = line.split("  ")
        assert checksum == native.sha(assets / name)


def test_collect_rejects_incomplete_matrix(tmp_path):
    assets = archives(tmp_path)
    next(assets.glob("*.zip")).unlink()
    with pytest.raises(ValueError, match="incomplete"):
        native.collect(VERSION, LIBRARIES, COMMIT, assets)
    assert not (assets / "SHA256SUMS").exists()


def test_collect_rejects_other_source_commit(tmp_path):
    assets = archives(tmp_path)
    with pytest.raises(ValueError, match="sources"):
        native.collect(VERSION, LIBRARIES, "4" * 40, assets)
    assert not (assets / "SHA256SUMS").exists()
