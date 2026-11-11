"""Carrier agent CLI; the same adapter implements terminal and SDK launches."""
import asyncio
import json
import os
import subprocess


def options(parser):
    parser.add_argument('--config', help='Agent Manager provider configuration')
    parser.add_argument('--agent-home', help='Agent Manager state root')
    parser.add_argument('--integration-home', help='Carrier adapter state root')
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--db', help='Local database served by Carrier')
    source.add_argument('--credentials', help='Existing Carrier identity; also supports remote services')
    parser.add_argument('provider', choices=['codex'])
    commands = parser.add_subparsers(dest='agent_action', required=True)
    for name in ('run', 'start', 'continue', 'reconcile', 'adopt'):
        item = commands.add_parser(name)
        if name == 'run': item.add_argument('profile')
        elif name in ('continue', 'adopt'):
            item.add_argument('session')
            if name == 'continue': item.add_argument('--profile')
        if name not in ('reconcile', 'adopt'):
            item.add_argument('--operation-id', help='UUID retry key; reuse to inspect the same launch')
            item.add_argument('--cwd')
            item.add_argument('--model')
            item.add_argument('--no-attach', action='store_true')


def command(args):
    try:
        from agent_manager import Client, Error
        from .client import CarrierAgents
    except ImportError as error:
        raise ValueError('Install aixand-carrier-mcp[agent-manager] in this Python environment') from error

    async def run():
        async with Client(args.provider, config=args.config, root=args.agent_home) as agents:
            adapter = CarrierAgents(agents, url=args.url, database=args.db,
                credentials=args.credentials, home=args.integration_home)
            if args.agent_action == 'adopt':
                print(json.dumps(await adapter.adopt_legacy(args.session), indent=2))
                return None
            if args.agent_action == 'reconcile':
                print(json.dumps(await adapter.reconcile(), indent=2))
                return None
            if args.native_arguments and args.agent_action == 'continue':
                raise ValueError('Continuation uses captured settings; forwarded arguments are not supported')
            selection = dict(idempotency_key=args.operation_id)
            if args.native_arguments: selection['args'] = args.native_arguments
            if args.cwd is not None: selection['cwd'] = args.cwd
            if args.model is not None: selection['model'] = args.model
            if args.agent_action == 'run': result = await adapter.spawn(profile=args.profile, **selection)
            elif args.agent_action == 'start': result = await adapter.start(**selection)
            else: result = await adapter.continue_session(args.session, profile=args.profile, **selection)
            print(f'Agent run: {result.run_id}', flush=True)
            print(f'Undercurrent session: {result.session_id}', flush=True)
            return result.session_id, dict(agents.runtime.connection_options)
    try: selected = asyncio.run(run())
    except Error as error: raise ValueError(str(error)) from error
    if selected is None or args.no_attach: return 0
    session, connection = selected
    return subprocess.call(['uc', 'attach', session],
                           env=os.environ | {'UNDERCURRENT_HOME': connection['home']})
