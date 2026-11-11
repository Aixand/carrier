"""Existing source receipts and new product stores must keep separate entry routes."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "carrier_dev", Path(__file__).resolve().parents[1] / "scripts/carrier_dev.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    "arguments",
    [
        ["install", "--prod"],
        ["reinstall"],
        ["uninstall"],
    ],
)
def test_existing_source_install_routes_keep_their_receipt_owner(arguments):
    assert module.legacy(arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        ["install"],
        ["uninstall", "--prefix=/tmp/products"],
        ["reinstall", "--artifact", "/tmp/release"],
        ["uninstall", "--product", "carrier"],
    ],
)
def test_product_arguments_cannot_route_to_the_source_uninstaller(arguments):
    assert not module.legacy(arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        ["doctor"],
        ["develop"],
        ["package"],
        ["install", "--prod"],
        ["install", "--prefix", "/tmp/products"],
        ["reinstall"],
    ],
)
def test_missing_dependency_stops_source_operations_before_changes(
    tmp_path, monkeypatch, capsys, arguments
):
    root = tmp_path / "carrier"
    root.mkdir()
    monkeypatch.setattr(module, "ROOT", root)

    def unexpected(*args, **kwargs):
        pytest.fail(
            "A missing dependency must be rejected before invoking an installer"
        )

    monkeypatch.setattr(module.subprocess, "call", unexpected)
    assert module.main(arguments) == 2
    assert "aixand-lib-filesystem" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == [root]


@pytest.mark.parametrize(
    "arguments",
    [
        ["--help"],
        ["install", "--artifact", "/tmp/release"],
        ["reinstall", "--artifact=/tmp/release"],
        ["verify", "--artifact", "/tmp/release"],
        ["uninstall"],
        ["uninstall", "--prefix", "/tmp/products", "--stopped"],
    ],
)
def test_help_artifacts_and_removal_do_not_require_source_dependency(
    tmp_path, monkeypatch, arguments
):
    monkeypatch.setattr(module, "ROOT", tmp_path / "carrier")
    calls = []
    monkeypatch.setattr(
        module.subprocess, "call", lambda argv, **kwargs: calls.append(argv) or 0
    )
    assert module.main(arguments) == 0
    assert len(calls) == 1


def test_source_dependency_must_be_the_expected_distribution(tmp_path, monkeypatch):
    root = tmp_path / "carrier"
    platform = tmp_path / "aixand-libraries/filesystem"
    platform.mkdir(parents=True)
    manifest = platform / "pyproject.toml"
    monkeypatch.setattr(module, "ROOT", root)
    manifest.write_text('[project]\nname = "another-package"\n')
    assert "Expected the aixand-lib-filesystem distribution" in module.source_error(
        ["develop"]
    )
    manifest.write_text('[project]\nname = "aixand-lib-filesystem"\n')
    assert module.source_error(["develop"]) is None
