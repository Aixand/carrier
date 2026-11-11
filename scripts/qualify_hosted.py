"""Check exact public hosted Carrier installers in disposable native homes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request


def fetch(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "Aixand-Carrier-Installer-Qualification/1.0"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        if not response.url.startswith("https://"):
            raise RuntimeError("Installer delivery must remain HTTPS")
        data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise RuntimeError("Oversized installer response")
        return data


def terminal_install(script, env, answer):
    """Keep piped shell source separate from the controlling terminal answer."""
    pid, terminal = os.forkpty()
    if pid == 0:
        os.environ.clear()
        os.environ.update(env)
        os.execvp("sh", ["sh", "-c", 'cat "$1" | sh', "hosted-check", str(script)])
    output = bytearray()
    sent = False
    deadline = time.monotonic() + 600
    try:
        while time.monotonic() < deadline:
            if not select.select([terminal], [], [], 0.2)[0]:
                continue
            try:
                chunk = os.read(terminal, 65536)
            except OSError as error:
                if error.errno == 5:  # PTY closes with EIO on Linux.
                    break
                raise
            if not chunk:
                break
            output.extend(chunk)
            if not sent and b"[y/N]" in output:
                os.write(terminal, (answer + "\n").encode())
                sent = True
        else:
            raise TimeoutError("Hosted interactive installation timed out")
    except BaseException:
        os.killpg(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        raise
    finally:
        os.close(terminal)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), output.decode(errors="replace")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    origin = "https://installer.aixand.org"
    project = json.loads(fetch(origin + "/api/v1/projects/carrier"))["project"]
    release = next(row for row in project["releases"] if row["version"] == args.version)
    windows = os.name == "nt"
    target = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}[
        platform.system()
    ]
    target += "-" + (
        "arm64" if platform.machine().lower() in ("aarch64", "arm64") else "x86_64"
    )
    target += "-gnu" if platform.system() == "Linux" else "-msvc" if windows else ""
    asset = release["assets"][target]
    report = dict(
        project="carrier",
        version=args.version,
        target=target,
        verified=False,
        checks=[],
        manifest_sha256=asset["manifestSha256"],
        product_release=asset["productRelease"],
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    logs = args.report.with_suffix(".logs")
    logs.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="carrier-hosted-") as temporary:
        root = Path(temporary)
        home, temp, store = root / "home", root / "tmp", root / "products"
        for directory in (home, temp, root / "runtime"):
            directory.mkdir()
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("AIXAND_", "UNDERCURRENT_", "CARRIER_", "XDG_"))
            and key.upper()
            not in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "PSMODULEPATH")
        }
        env.update(
            HOME=str(home),
            USERPROFILE=str(home),
            LOCALAPPDATA=str(home / "AppData/Local"),
            APPDATA=str(home / "AppData/Roaming"),
            XDG_DATA_HOME=str(home / "data"),
            XDG_CONFIG_HOME=str(home / "config"),
            XDG_CACHE_HOME=str(home / "cache"),
            XDG_RUNTIME_DIR=str(root / "runtime"),
            UNDERCURRENT_HOME=str(root / "uc"),
            CARRIER_DATABASE=str(root / "carrier.db"),
            AIXAND_INSTALLER_CACHE=str(root / "helper"),
            AIXAND_SHARED_PRODUCT_PREFIX=str(store),
            TMPDIR=str(temp),
            TEMP=str(temp),
            TMP=str(temp),
            PIP_NO_INDEX="1",
            UV_OFFLINE="1",
        )
        if windows:
            system = Path(os.environ["SystemRoot"]) / "System32"
            shell = system / "WindowsPowerShell/v1.0/powershell.exe"
            env["PATH"] = str(system)
        else:
            tools = root / "tools"
            tools.mkdir()
            for name in (
                "sh",
                "cat",
                "uname",
                "curl",
                "tar",
                "gzip",
                "awk",
                "mktemp",
                "mkdir",
                "ln",
                "readlink",
                "rm",
                "mv",
                "rmdir",
                "dirname",
                "sha256sum",
                "shasum",
            ):
                found = shutil.which(name)
                if found:
                    (tools / name).symlink_to(found)
            env["PATH"] = str(tools)
            shell = tools / "sh"
        script = root / ("install.ps1" if windows else "install.sh")
        endpoint = "/carrier/install.ps1" if windows else "/carrier"
        script.write_bytes(
            fetch(
                origin
                + endpoint
                + "?"
                + urllib.parse.urlencode(dict(version=args.version))
            )
        )
        report["script_sha256"] = hashlib.sha256(script.read_bytes()).hexdigest()

        def record(name, status, output, expected=0):
            (logs / (name + ".log")).write_text(output, encoding="utf-8")
            if (expected == 0 and status != 0) or (expected != 0 and status == 0):
                raise RuntimeError(
                    f"{name} failed with exit {status}: {output[-2000:]}"
                )
            report["checks"].append(name)
            print("PASS " + name, flush=True)
            return output

        def run(name, command, expected=0):
            process = subprocess.Popen(
                list(map(str, command)),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=not windows,
            )
            try:
                output = process.communicate(timeout=600)[0]
            except BaseException:
                if windows:
                    subprocess.run(
                        [
                            str(system / "taskkill.exe"),
                            "/PID",
                            str(process.pid),
                            "/T",
                            "/F",
                        ],
                        capture_output=True,
                    )
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise
            return record(name, process.returncode, output, expected)

        def wrapper(name, mode, extra=(), expected=0, selected=script):
            if windows:
                command = [
                    shell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    selected,
                    "-Mode",
                    mode,
                    "-Prefix",
                    store,
                    *extra,
                ]
                if mode == "Install":
                    command.append("-NoCommands")
            else:
                command = [
                    shell,
                    selected,
                    "--" + mode.lower(),
                    "--prefix",
                    store,
                    *extra,
                ]
            return run(name, command, expected)

        def interactive(name, answer, expected=0):
            if windows:
                driver = root / (name + ".ps1")
                literal = lambda value: "'" + str(value).replace("'", "''") + "'"
                driver.write_text(
                    "$ErrorActionPreference = 'Stop'\nfunction Read-Host { param($Prompt) "
                    + literal(answer)
                    + " }\n& "
                    + literal(script)
                    + " -Prefix "
                    + literal(store)
                    + " -NoCommands\n"
                )
                return run(
                    name,
                    [shell, "-NoProfile", "-NonInteractive", "-File", driver],
                    expected,
                )
            status, output = terminal_install(script, env, answer)
            return record(name, status, output, expected)

        def receipt(prefix):
            return json.loads((prefix / "installation-receipt.json").read_text())

        try:
            interactive("cancel", "n", expected=1)
            assert not store.exists() and not list(temp.iterdir())
            wrapper("plan", "Plan")
            assert not store.exists()
            (bundle,) = temp.glob("aixand-install*/payload/" + asset["archiveRoot"])
            manifest = bundle / "artifacts/release-manifest.json"
            assert (
                hashlib.sha256(manifest.read_bytes()).hexdigest()
                == asset["manifestSha256"]
            )
            assert (
                json.loads(manifest.read_text())["products"]["carrier"]["release"]
                == asset["productRelease"]
            )
            damaged = root / ("damaged" + script.suffix)
            damaged.write_text(script.read_text().replace(asset["sha256"], "0" * 64))
            wrapper(
                "reject-hash",
                "DownloadOnly" if windows else "download-only",
                expected=1,
                selected=damaged,
            )
            retained = set(temp.iterdir())
            command = store / "bin" / ("carrier.exe" if windows else "carrier")
            cli = home / ".local/bin/carrier"
            if not windows:
                cli.parent.mkdir(parents=True)
                cli.write_text("foreign command")
            interactive("install", "y")
            assert set(temp.iterdir()) == retained
            shared = receipt(store)
            assert shared["scope"] == "shared" and shared["owner"] == "user"
            assert set(shared["products"]) == {"carrier"}
            installed = shared["products"]["carrier"]
            assert installed["product"]["release"] == asset["productRelease"]
            run("version", [command, "--version"])
            run("help", [command, "--help"])
            if not windows:
                assert cli.read_text() == "foreign command"
                cli.unlink()
            database = Path(env["CARRIER_DATABASE"])
            database.write_text("preserve data")
            wrapper("repeat-install", "Install")
            assert (
                receipt(store)["products"]["carrier"]["payload"] == installed["payload"]
            )
            if not windows:
                assert cli.is_symlink() and cli.resolve() == command.resolve()
            private = root / "application/products"
            options = (
                ["-Scope", "private", "-Owner", "hosted-check", "-Prefix", private]
                if windows
                else [
                    "--scope",
                    "private",
                    "--owner",
                    "hosted-check",
                    "--prefix",
                    private,
                ]
            )
            # Explicit prefix replaces the shared default; avoid duplicate PS parameters.
            if windows:
                run(
                    "private-install",
                    [
                        shell,
                        "-NoProfile",
                        "-NonInteractive",
                        "-File",
                        script,
                        "-Mode",
                        "Install",
                        *options,
                        "-NoCommands",
                    ],
                )
            else:
                wrapper("private-install", "Install", options)
            assert (
                receipt(private)["scope"] == "private"
                and receipt(private)["owner"] == "hosted-check"
            )
            assert (
                receipt(store)["products"]["carrier"]["payload"] == installed["payload"]
            )
            bootstrap = (
                bundle / "bootstrap" / ("bootstrap.ps1" if windows else "bootstrap.sh")
            )
            launcher = (
                [shell, "-NoProfile", "-NonInteractive", "-File", bootstrap]
                if windows
                else [shell, bootstrap]
            )
            for name, prefix in (
                ("private-uninstall", private),
                ("shared-uninstall", store),
            ):
                run(
                    name,
                    [
                        *launcher,
                        "uninstall",
                        "--product",
                        "carrier",
                        "--prefix",
                        prefix,
                        "--stopped",
                    ],
                )
                assert "carrier" not in receipt(prefix)["products"]
                assert database.read_text() == "preserve data"
            assert not command.exists()
            report["verified"] = True
        except BaseException as error:
            report["error"] = str(error)
            raise
        finally:
            args.report.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
