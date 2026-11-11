"""Installer failure and ownership checks; no package downloads required."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import dev


def make_release(root, name):
    environment = root / name
    (environment / dev.BIN).mkdir(parents=True)
    (environment / 'pyvenv.cfg').write_text('home = test-python\n')
    (environment / dev.BIN / dev.COMMAND).write_bytes(name.encode())
    return environment


@pytest.fixture
def installed(tmp_path):
    root = tmp_path / 'private environments'
    command = tmp_path / 'install bin' / dev.COMMAND
    command.parent.mkdir()
    environment = make_release(root, 'release-original')
    dev.publish_current(environment, root)
    dev.publish_command(environment, root, command)
    return root, command, environment


@pytest.mark.parametrize('failure', ['venv', 'pip', 'probe', 'publish'])
def test_failed_reinstall_preserves_working_install(installed, monkeypatch, failure):
    root, command, original = installed
    original_command = command.read_bytes()

    def run(arguments, **kwargs):
        if arguments[1:3] == ['-m', 'venv']:
            stage = 'venv'
            make_release(root, Path(arguments[3]).name)
        elif arguments[1:3] == ['-m', 'pip']:
            stage = 'pip'
        else:
            stage = 'probe'
        if failure == stage:
            raise subprocess.CalledProcessError(1, arguments)

    monkeypatch.setattr(dev.subprocess, 'run', run)
    if failure == 'publish':
        def deny_replace(source, destination):
            raise PermissionError('command in use')
        if dev.WINDOWS:
            replace = os.replace

            def replace_command(source, destination):
                if destination == command:
                    deny_replace(source, destination)
                replace(source, destination)

            monkeypatch.setattr(dev.os, 'replace', replace_command)
        else:
            publish_link = dev.publish_link

            def replace_command(source, destination):
                if destination == command:
                    deny_replace(source, destination)
                publish_link(source, destination)

            monkeypatch.setattr(dev, 'publish_link', replace_command)

    with pytest.raises((subprocess.CalledProcessError, PermissionError)):
        dev.install(root, command, True)

    assert command.read_bytes() == original_command
    assert dev.current_environment(root) == original
    assert list(root.glob('release-*')) == [original]
    assert list(command.parent.iterdir()) == [command]
    assert not list(root.glob('.carrier-current-*'))


def test_uninstall_preserves_state_and_unrelated_files(installed):
    root, command, _ = installed
    make_release(root, 'release-older')
    state = root / 'carrier.db'
    state.write_bytes(b'preserved database')
    unrelated = command.parent / 'another-command'
    unrelated.write_bytes(b'preserved command')

    dev.uninstall(root, command)
    dev.uninstall(root, command)

    assert not dev.exists(command)
    assert not dev.exists(root / 'current')
    assert not list(root.glob('release-*'))
    assert state.read_bytes() == b'preserved database'
    assert unrelated.read_bytes() == b'preserved command'


def test_unmanaged_command_is_never_replaced_or_removed(installed):
    root, command, environment = installed
    command.unlink()
    command.write_bytes(b'another installation')

    for action in (lambda: dev.install(root, command, True),
                   lambda: dev.uninstall(root, command)):
        with pytest.raises(RuntimeError, match='unmanaged command'):
            action()
        assert command.read_bytes() == b'another installation'
        assert environment.is_dir()


def test_unexpected_environment_blocks_uninstall_before_changes(installed):
    root, command, environment = installed
    (root / 'release-unmanaged').mkdir()
    with pytest.raises(RuntimeError, match='unexpected environment'):
        dev.uninstall(root, command)
    assert dev.owned_command(command, root)
    assert environment.is_dir()


@pytest.mark.parametrize('value', ['relative', '.', 'bad\npath', 'bad\rpath'])
def test_directory_overrides_require_absolute_paths(monkeypatch, value):
    monkeypatch.setenv('CARRIER_DEV_ENV_DIR', value)
    with pytest.raises(RuntimeError, match='absolute path'):
        dev.configured_path('CARRIER_DEV_ENV_DIR', Path.home())


def test_directory_override_rejects_normalized_root(monkeypatch, tmp_path):
    value = Path(tmp_path.anchor) / 'directory' / '..'
    monkeypatch.setenv('CARRIER_DEV_ENV_DIR', str(value))
    with pytest.raises(RuntimeError, match='filesystem root'):
        dev.configured_path('CARRIER_DEV_ENV_DIR', tmp_path)


@pytest.mark.skipif(not dev.WINDOWS, reason='Windows current file and path syntax')
@pytest.mark.parametrize('value', ['../release-outside', r'..\release-outside', r'C:\release-outside'])
def test_windows_current_cannot_escape_environment_directory(installed, value):
    root, command, environment = installed
    (root / 'current').write_text(value)
    with pytest.raises(RuntimeError, match='Unexpected environment target'):
        dev.uninstall(root, command)
    assert command.is_file()
    assert environment.is_dir()


@pytest.mark.skipif(not dev.WINDOWS, reason='Windows file locking')
def test_concurrent_installer_is_rejected(installed):
    import msvcrt

    root, command, environment = installed
    (root / dev.MARKER).write_text(dev.IDENTITY)
    with (root / '.install.lock').open('a+b') as lock:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        result = subprocess.run(
            [sys.executable, str(dev.PROJECT / 'scripts/dev.py'), 'uninstall'],
            env=os.environ | {'CARRIER_DEV_ENV_DIR': str(root),
                              'CARRIER_DEV_INSTALL_DIR': str(command.parent)},
            text=True, capture_output=True, timeout=15,
        )
    assert result.returncode == 1
    assert 'Another Carrier installation is running' in result.stderr
    assert dev.owned_command(command, root)
    assert environment.is_dir()
