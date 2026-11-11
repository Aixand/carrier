import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from carrier.service import Store, create_app


def main():
    default_db = str(Path.home() / '.aixand/carrier/carrier.db')
    parser = argparse.ArgumentParser(description="Carrier agent session messaging")
    from . import __version__
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Run the shared HTTP service")
    serve.add_argument("--db", default=default_db)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    provision = commands.add_parser("session", help="Create a session and private credential file")
    provision.add_argument("address")
    provision.add_argument("--name", help="Optional readable session name (case-sensitive)")
    provision.add_argument("--db", default=default_db)
    provision.add_argument("--credentials", required=True)
    budget_source = commands.add_parser("budget-source", help="Create a budget monitor identity with a fixed recipient")
    budget_source.add_argument("address")
    budget_source.add_argument("--to", required=True, help="Exact existing recipient address")
    budget_source.add_argument("--db", default=default_db)
    budget_source.add_argument("--credentials", required=True)
    adapter = commands.add_parser("mcp", help="Run a per-session stdio MCP adapter")
    adapter.add_argument("--url", default="http://127.0.0.1:8765")
    adapter.add_argument("--credentials", required=True)
    adapter.add_argument("--binding", help="Optional Agent Manager startup binding gate")
    adapter.add_argument("--binding-hook", help="Agent Manager lifecycle binding handler (requires --binding)")
    check = commands.add_parser("check", help="Verify service access with existing session credentials")
    check.add_argument("--url", default="http://127.0.0.1:8765")
    check.add_argument("--credentials", required=True)
    check.add_argument("--budget-source", action="store_true", help="Verify budget ingestion identity and fixed route")
    status = commands.add_parser("status", help="Check whether the Carrier backend is reachable")
    status.add_argument("--url", default="http://127.0.0.1:8765")
    status.add_argument("--json", action="store_true", help="Print a machine-readable health result")
    from carrier.integrations.agent_manager.cli import options as agent_options
    agent_options(commands.add_parser('agent', help='Launch an agent with Carrier (requires the agent-manager extra)'))
    argv = sys.argv[1:]
    forwarded = []
    if argv[:1] == ['agent'] and '--' in argv:
        at = argv.index('--')
        forwarded, argv = argv[at + 1:], argv[:at]
    args = parser.parse_args(argv)
    args.native_arguments = forwarded
    if args.command == 'agent':
        from carrier.integrations.agent_manager.cli import command as agent_command
        try: raise SystemExit(agent_command(args))
        except (OSError, ValueError) as error: parser.error(str(error))
    elif args.command == "serve":
        import uvicorn
        uvicorn.run(create_app(args.db), host=args.host, port=args.port)
    elif args.command in ("session", "budget-source"):
        path = Path(args.credentials)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            parser.error("Credential file already exists; use it to resume, or choose another path.")
        try:
            with os.fdopen(fd, "w") as stream:
                from aixand_filesystem import secure_file
                secure_file(stream)
                store = Store(args.db)
                token = (store.provision_budget(args.address, args.to) if args.command == 'budget-source'
                         else store.provision(args.address, args.name))
                json.dump({"address": args.address, "token": token}, stream)
        except (ValueError, sqlite3.IntegrityError) as exc:
            path.unlink()
            parser.error(f"Cannot create session (address may already exist): {exc}")
        print(f"Created {args.address}; credentials saved to {path}")
    elif args.command == "status":
        import httpx
        healthy = False
        try:
            with httpx.Client(trust_env=False, timeout=5) as client:
                response = client.get(args.url.rstrip('/') + '/health')
                healthy = response.status_code == 200 and response.json() == {'status': 'ok', 'service': 'carrier'}
        except (ValueError, httpx.HTTPError):
            pass
        result = {'status': 'running' if healthy else 'unavailable', 'url': args.url}
        print(json.dumps(result) if args.json else f"Carrier {result['status']} at {args.url}")
        if not healthy:
            raise SystemExit(1)
    elif args.command == "check":
        import httpx
        try:
            credentials = json.loads(Path(args.credentials).read_text())
            with httpx.Client(trust_env=False, timeout=5) as client:
                response = client.get(args.url.rstrip("/") + ("/budget-source" if args.budget_source else "/whoami"), headers={"Authorization": "Bearer " + credentials["token"]})
                response.raise_for_status()
                identity = response.json()
                if identity["address"] != credentials["address"]:
                    raise ValueError("Credential address mismatch")
                print(json.dumps(identity))
        except (OSError, ValueError, KeyError, httpx.HTTPError):
            parser.error("Carrier unavailable or session credentials invalid; restore the service/credentials rather than replacing the identity.")
    else:
        from carrier.adapter import create_adapter
        if args.binding_hook and not args.binding:
            parser.error('--binding-hook requires --binding')
        credentials = json.loads(Path(args.credentials).read_text())
        create_adapter(args.url, credentials["token"], args.binding, args.binding_hook).run(transport="stdio")


if __name__ == "__main__":
    main()
