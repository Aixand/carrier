"""Install Carrier from source into a private environment."""

import argparse
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

PROJECT = Path(__file__).resolve().parents[1]
MARKER = ".carrier-dev-install"
IDENTITY = "carrier-dev-install-v1\n"
WINDOWS = sys.platform == 'win32'
DEV_SCRIPT = r'.\dev.ps1' if WINDOWS else './dev.sh'
BIN = 'Scripts' if WINDOWS else 'bin'
PYTHON = 'python.exe' if WINDOWS else 'python'
COMMAND = 'carrier.exe' if WINDOWS else 'carrier'


def exists(path):
    return os.path.lexists(path)


def linked(path):
    return path.is_symlink() or (
        WINDOWS and exists(path)
        and bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    )


def configured_path(variable, default):
    path = Path(os.environ.get(variable, str(default))).expanduser()
    if not path.is_absolute() or '\n' in str(path) or '\r' in str(path):
        raise RuntimeError(f'{variable} must be an absolute path without newlines')
    for candidate in (path, *path.parents) if WINDOWS else (path,):
        if linked(candidate):
            raise RuntimeError(f'{variable} must not use a linked path: {candidate}')
    resolved = path.resolve()
    if resolved == Path(resolved.anchor):
        raise RuntimeError(f'{variable} must not be a filesystem root')
    return resolved


def current_environment(root):
    current = root / 'current'
    if not exists(current):
        return None
    if WINDOWS:
        if linked(current) or not current.is_file():
            raise RuntimeError(f'Refusing to replace an unmanaged path: {current}')
        name = current.read_text(encoding='utf-8').strip()
        if not name or Path(name).name != name:
            raise RuntimeError(f'Unexpected environment target: {current}')
        target = root / name
    else:
        if not current.is_symlink():
            raise RuntimeError(f'Refusing to replace an unmanaged path: {current}')
        target = current.resolve()
    if target.parent != root or not target.name.startswith('release-') or linked(target):
        raise RuntimeError(f'Unexpected environment target: {current}')
    return target


def owned_command(command, root):
    if WINDOWS:
        environment = current_environment(root)
        source = environment / BIN / COMMAND if environment else None
        return (not linked(command) and command.is_file() and source is not None
                and source.is_file() and command.read_bytes() == source.read_bytes())
    return command.is_symlink() and os.readlink(command) == str(root / 'current/bin/carrier')


def preflight(root, command, replace):
    environment = current_environment(root)
    if exists(command):
        if not replace:
            raise RuntimeError(f'{command} already exists; use {DEV_SCRIPT} reinstall')
        if not owned_command(command, root):
            raise RuntimeError(f'Refusing to replace an unmanaged command: {command}')
    if environment is not None and not replace:
        raise RuntimeError(f'Carrier is already installed in {root}; use {DEV_SCRIPT} reinstall')


def publish_link(target, destination):
    temporary = destination.with_name('.carrier-link-' + uuid.uuid4().hex)
    try:
        temporary.symlink_to(target)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def publish_current(environment, root):
    if not WINDOWS:
        publish_link(environment, root / 'current')
        return
    temporary = root / ('.carrier-current-' + uuid.uuid4().hex)
    try:
        temporary.write_text(environment.name + '\n', encoding='utf-8')
        os.replace(temporary, root / 'current')
    finally:
        temporary.unlink(missing_ok=True)


def publish_command(environment, root, command):
    if not WINDOWS:
        publish_link(root / 'current/bin/carrier', command)
        return
    # pip's native launcher embeds the absolute venv interpreter path, so it can
    # be copied into PATH without symlinks, activation, or administrator access.
    temporary = command.with_name('.carrier-command-' + uuid.uuid4().hex + '.exe')
    try:
        shutil.copyfile(environment / BIN / COMMAND, temporary)
        os.replace(temporary, command)
    finally:
        temporary.unlink(missing_ok=True)


def validate_environment(environment, root):
    if (linked(environment) or environment.resolve().parent != root.resolve()
            or not environment.name.startswith('release-')
            or not (environment / 'pyvenv.cfg').is_file()):
        raise RuntimeError(f'Refusing to remove an unexpected environment: {environment}')


def remove_environment(environment, root):
    # Check the resolved deletion target before recursively removing any files.
    if (linked(environment) or environment.resolve().parent != root.resolve()
            or not environment.name.startswith('release-')):
        raise RuntimeError(f'Refusing to remove an unexpected environment: {environment}')
    shutil.rmtree(environment)


def install(root, command, replace):
    preflight(root, command, replace)
    previous = current_environment(root)
    environment = Path(tempfile.mkdtemp(prefix='release-', dir=root))
    published = False
    try:
        subprocess.run([sys.executable, '-m', 'venv', str(environment)], check=True)
        subprocess.run([
            str(environment / BIN / PYTHON), '-m', 'pip', 'install',
            '--disable-pip-version-check', str(PROJECT.parent / 'aixand-libraries/filesystem'), str(PROJECT),
        ], cwd=PROJECT, check=True)
        # Probe outside the checkout so source imports cannot hide a broken wheel.
        subprocess.run([str(environment / BIN / COMMAND), '--help'],
                       cwd=environment, check=True, stdout=subprocess.DEVNULL)
        command.parent.mkdir(parents=True, exist_ok=True)
        preflight(root, command, replace)
        try:
            publish_current(environment, root)
            publish_command(environment, root, command)
            published = True
        except BaseException:
            if previous is None:
                (root / 'current').unlink(missing_ok=True)
            else:
                publish_current(previous, root)
            raise
    finally:
        if not published:
            remove_environment(environment, root)
    print(f'{"Reinstalled" if replace else "Installed"} Carrier: {command}')
    if WINDOWS:
        print('No virtualenv activation is needed.')
    else:
        print(f'Add {command.parent} to PATH; no virtualenv activation is needed.')
    print('Restart the Carrier service and MCP adapters to load this installation.')
    print('Previous environments are retained until uninstall for existing processes.')


def uninstall(root, command):
    preflight(root, command, True)
    # Remove only installer-created environments, never the surrounding state directory.
    environments = list(root.glob('release-*'))
    for environment in environments:
        validate_environment(environment, root)
    if owned_command(command, root):
        command.unlink()
    (root / 'current').unlink(missing_ok=True)
    for environment in environments:
        remove_environment(environment, root)
    print(f'Uninstalled Carrier from {command}')
    print('Databases, credentials, and service configuration were preserved.')


def main():
    parser = argparse.ArgumentParser(
        prog=DEV_SCRIPT,
        description='Install Carrier from this checkout (Windows/Linux/macOS, Python 3.11+).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f'''Commands:
  {DEV_SCRIPT} install --prod   Install a standalone package and its runtime dependencies.
  {DEV_SCRIPT} reinstall       Build and switch to a fresh installation (also accepts --prod).
  {DEV_SCRIPT} uninstall       Remove installed environments and command; preserve product state.

Environment:
  CARRIER_DEV_PYTHON       Python executable (auto-detected on Windows; otherwise python3)
  CARRIER_DEV_INSTALL_DIR  Command directory (default: ~/.local/bin)
  CARRIER_DEV_ENV_DIR      Private environments (default: ~/.aixand/carrier/dev-install)

On Windows, dev.ps1 install/reinstall adds the command directory to your user
PATH and current PowerShell process. Run dev.ps1 directly to use carrier in
that shell immediately; a child powershell -File cannot update its parent shell.

Directory overrides must be absolute paths. Stop the service and MCP adapters
before uninstalling. This script does not install or manage a background service.''',
    )
    parser.add_argument('action', choices=['install', 'reinstall', 'uninstall', 'help'])
    parser.add_argument('--prod', action='store_true', help='Required for a new source installation')
    args = parser.parse_args()
    if args.action == 'help':
        parser.print_help()
        return
    if args.action == 'install' and not args.prod:
        parser.error('install requires --prod')
    if args.action == 'uninstall' and args.prod:
        parser.error('uninstall does not accept --prod')
    if sys.version_info < (3, 11) or sys.platform not in ('linux', 'darwin', 'win32'):
        raise RuntimeError('This installer requires Python 3.11+ on Windows, Linux, or macOS')

    root = configured_path('CARRIER_DEV_ENV_DIR', Path.home() / '.aixand/carrier/dev-install')
    command = configured_path('CARRIER_DEV_INSTALL_DIR', Path.home() / '.local/bin') / COMMAND
    if root == command.parent or root in command.parents:
        raise RuntimeError('The command directory must be outside the private environment directory')
    if not root.exists() and args.action == 'uninstall':
        if exists(command):
            raise RuntimeError(f'No managed environment found; leaving {command} untouched')
        print('Carrier development installation is already absent.')
        return
    if root.exists():
        marker = root / MARKER
        if not root.is_dir() or not marker.is_file() or linked(marker) or marker.read_text() != IDENTITY:
            raise RuntimeError(f'Refusing to use an unmanaged environment directory: {root}')
    else:
        preflight(root, command, args.action == 'reinstall')
        root.mkdir(parents=True, mode=0o700)
        (root / MARKER).write_text(IDENTITY)
    with (root / '.install.lock').open('a+b') as lock:
        try:
            if WINDOWS:
                import msvcrt
                # Windows locks a byte range; all installer processes use byte 0.
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('Another Carrier installation is running') from None
        if args.action == 'uninstall':
            uninstall(root, command)
        else:
            install(root, command, args.action == 'reinstall')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f'carrier dev installer: {error}', file=sys.stderr)
        sys.exit(1)
