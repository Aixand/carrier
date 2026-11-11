"""Durable Carrier preparation around Agent Manager's public async SDK."""
import asyncio
from copy import deepcopy
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import threading
import httpx
from aixand_filesystem import private_directory
import uuid
from urllib.parse import urlsplit

from carrier import Client as CarrierClient, ensure_session
from .storage import atomic, async_lease, lease, read


class CarrierAgents:
    def __init__(self, agents, *, url='http://127.0.0.1:8765', database=None,
                 credentials=None, home=None, monitor=True, transport=None):
        if sys.version_info >= (3, 15):
            raise ValueError('The agent integration currently requires Python 3.11–3.14')
        self.agents = agents
        self.manager = agents.manager
        if not all(callable(getattr(agents, name, None)) for name in ('execution_status', 'select_profile', 'validate_native_config')):
            raise ValueError('Upgrade Agent Manager to a build with external launch integration contracts')
        if self.manager.provider != 'codex':
            raise ValueError('The Carrier agent adapter is currently qualified for Codex only')
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Carrier URL must be HTTP(S) without credentials, query or fragment')
        if database is not None and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Local database provisioning requires a local Carrier service; supply existing credentials for remote services')
        if database is None and credentials is None:
            raise ValueError('Supply the local Carrier database or existing credentials')
        self.url = url.rstrip('/')
        self.database = str(Path(database).expanduser().resolve()) if database is not None else None
        self.credentials = str(Path(credentials).expanduser().resolve()) if credentials is not None else None
        namespace = hashlib.sha256(str(self.manager.state_path.resolve()).encode()).hexdigest()[:24]
        self.root = Path(home or Path.home() / '.aixand/carrier/agent-integration').expanduser().absolute() / namespace
        self.monitor = monitor
        self._transport = transport

    def _monitor(self, path):
        if not self.monitor: return
        log = path.with_suffix('.monitor.log')
        fd = os.open(log, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            process = subprocess.Popen([sys.executable, '-m', 'carrier.integrations.agent_manager', 'monitor', str(path)],
                             stdin=subprocess.DEVNULL, stdout=fd, stderr=fd, start_new_session=True)
            threading.Thread(target=process.wait, daemon=True).start()
        except OSError as error:
            from agent_manager import LaunchError
            raise LaunchError('Carrier monitor could not start; reconcile the adapter without relaunching', read(path)['execution']['run_id']) from error
        finally: os.close(fd)

    async def _identity(self, record):
        # Verify availability before local provisioning mutates any identity.
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=5, transport=self._transport) as health:
                response = await health.get(record['url'].rstrip('/') + '/health')
                response.raise_for_status()
                if response.json() != {'status': 'ok', 'service': 'carrier'}:
                    raise ValueError('Unexpected service health response')
        except (httpx.HTTPError, ValueError) as error:
            raise ValueError('Carrier is unavailable or unhealthy; restore the service before provisioning or launching') from error
        if not Path(record['credentials']).is_file():
            if record.get('existing'):
                raise ValueError('Original Carrier credentials are missing; restore them rather than creating a replacement identity')
            await asyncio.to_thread(ensure_session, database=record['database'],
                                    credentials=record['credentials'], address=record['address'])
        async with CarrierClient(url=record['url'], credentials=record['credentials'], transport=self._transport) as carrier:
            identity = await carrier.whoami()
        if identity['address'] != record['address']:
            raise ValueError('Carrier credentials do not match the captured conversation identity')

    def _settings(self, path):
        hook = str(Path(__file__).with_name('binding.py').resolve())
        args = ['-m', 'carrier', 'mcp', '--url', read(path)['record']['url'], '--credentials', read(path)['record']['credentials'],
                '--binding', str(path), '--binding-hook', hook]
        # Values are structured native TOML objects, not shell commands.
        definition = dict(type='mcp_tool', server='carrier', tool='bind_conversation',
                          input=dict(session_id='${session_id}', hook_event_name='${hook_event_name}'))
        return {'mcp_servers.carrier.command': sys.executable, 'mcp_servers.carrier.args': args,
                'mcp_servers.carrier.enabled': True,
                'hooks.SessionStart': [dict(matcher='startup|resume|clear', hooks=[definition])],
                'hooks.PreToolUse': [dict(matcher='.*', hooks=[definition])],
                'hooks.UserPromptSubmit': [dict(hooks=[definition])], 'hooks.Stop': [dict(hooks=[definition])]}

    async def spawn(self, *, profile=None, idempotency_key=None, **options):
        return await self._launch(None, profile=profile, idempotency_key=idempotency_key, options=options)

    async def start(self, *, idempotency_key=None, **options):
        options = deepcopy(options)
        options['cwd'] = str(Path(options.get('cwd') or os.getcwd()).expanduser().resolve())
        entrypoint = hashlib.sha256(json.dumps(options, sort_keys=True, allow_nan=False).encode()).hexdigest()
        if idempotency_key is not None:
            operation = uuid.UUID(str(idempotency_key)).hex
            path = self.root / 'operations' / (operation + '.json')
            if path.exists():
                row = read(path)
                if row.get('start_intent') != entrypoint:
                    raise ValueError('Carrier operation key was reused with different startup intent')
                from agent_manager import RunNotFoundError, LaunchError
                try: run = await self.agents.get(operation)
                except RunNotFoundError:
                    captured = row['startup']
                    destination = self.manager.resolve_agent_target(row['execution']['environment_id'])
                    if not destination['aliases']: raise ValueError('The original execution environment needs an alias before retrying')
                    target = self.manager.resolve_profile(destination['aliases'][0])
                    options.setdefault('expected_revision', captured['revision'])
                    if captured['model'] is not None: options.setdefault('model', captured['model'])
                    return await self._launch(None, profile=target, idempotency_key=operation,
                        options=options, start_intent=entrypoint, startup=captured, request_profile=captured['profile'])
                except LaunchError:
                    self._monitor(path)
                    raise
                self._monitor(path)
                return run
        selected = await self.agents.select_profile(model=options.get('model'), args=options.get('args', ()))
        target = self.manager.resolve_profile(selected['profile'])
        if target.environment_id != selected['environment_id']:
            raise ValueError('Selected environment changed; select again')
        options.setdefault('expected_revision', selected['environment_revision'])
        if selected['selection'].get('model') is not None:
            options.setdefault('model', selected['selection']['model'])
        captured = dict(profile=str(target), revision=selected['environment_revision'], model=selected['selection'].get('model'))
        return await self._launch(None, profile=target, idempotency_key=idempotency_key,
                                  options=options, start_intent=entrypoint, startup=captured)

    async def continue_session(self, session, *, profile=None, idempotency_key=None, **options):
        rows = await self.agents.sessions()
        matches = [row for row in rows if session in (row['ref'], row['native_id'])]
        if len(matches) != 1: raise ValueError('Choose one unambiguous retained native session reference')
        saved = matches[0]
        if profile is None:
            target = self.manager.resolve_agent_target(saved['origin_environment_id'])
            if not target['aliases']: raise ValueError('Select an execution profile for this unnamed source environment')
            profile = target['aliases'][0]
        return await self._launch(saved, profile=profile, idempotency_key=idempotency_key, options=options)

    async def _launch(self, session, *, profile, idempotency_key, options, start_intent=None, startup=None, request_profile=None):
        operation = uuid.UUID(str(idempotency_key)).hex if idempotency_key is not None else uuid.uuid4().hex
        options = deepcopy(options)
        if options.get('mode', 'terminal') != 'terminal' or options.get('app_server_run_id') is not None:
            raise ValueError('Carrier currently supports independent terminal launches only')
        if any(key in options for key in ('thread_id', 'resume_id')) or any(key.startswith('_') for key in options):
            raise ValueError('Use CarrierAgents.continue_session for retained conversations')
        inspect.signature(self.agents.spawn).bind(profile=profile, idempotency_key=operation, **options)
        arguments = options.get('args', ())
        if isinstance(arguments, (str, bytes)) or not all(isinstance(value, str) for value in arguments):
            raise ValueError('args must be a sequence of strings')
        cwd = str(Path(options.get('cwd') or (session['cwd'] if session else os.getcwd())).expanduser().resolve())
        if session and cwd != str(Path(session['cwd']).resolve()): raise ValueError('Continuation requires its captured working directory')
        if not Path(cwd).is_dir(): raise ValueError('Working directory does not exist')
        options['cwd'] = cwd
        native = self.manager.validate_native_config(options.get('native_config'))
        def key_path(key):
            node, result = tomllib.loads(key + '=0'), []
            while isinstance(node, dict):
                key, node = next(iter(node.items()))
                result.append(key)
            return tuple(result)
        reserved = [('mcp_servers', 'carrier'), ('hooks', 'SessionStart'), ('hooks', 'PreToolUse'),
                    ('hooks', 'UserPromptSubmit'), ('hooks', 'Stop')]
        for key in native:
            selected = key_path(key)
            if any(selected[:len(owner)] == owner or owner[:len(selected)] == selected for owner in reserved):
                raise ValueError('Native configuration conflicts with Carrier settings')
        request = dict(provider=self.manager.provider, profile=request_profile if request_profile is not None else str(profile) if profile is not None else None,
                       source=session['ref'] if session else None, options=options)
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, allow_nan=False).encode()).hexdigest()
        path = self.root / 'operations' / (operation + '.json')
        private_directory(self.root)
        async with async_lease(path.with_suffix('.operation.lock')):
            if path.exists():
                row = read(path)
                if row['request_digest'] != digest: raise ValueError('Carrier operation key was reused with different launch intent')
                from agent_manager import RunNotFoundError, LaunchError
                try:
                    run = await self.agents.get(operation)
                except RunNotFoundError: pass
                except LaunchError:
                    self._monitor(path)
                    raise
                else:
                    self._monitor(path)
                    return run
                if row['status'] in ('closed', 'blocked'): raise ValueError('This Carrier operation is closed; use a new operation key')
                target = self.manager.resolve_profile(profile)
                if target.environment_id != row['execution']['environment_id']:
                    raise ValueError('Original execution environment changed; do not retarget the operation')
            else:
                target = self.manager.resolve_profile(profile)
                existing = self.root / 'threads' / (session['native_id'] + '.json') if session else None
                record = read(existing) if existing is not None and existing.exists() else None
                if record is None:
                    address = 'codex-' + uuid.uuid5(uuid.NAMESPACE_URL, str(self.root) + ':' + operation).hex
                    credential_path = self.credentials or str(self.root / 'credentials' / (address + '.json'))
                    if self.credentials:
                        address = read(self.credentials)['address']
                    record = dict(address=address, credentials=credential_path, url=self.url,
                                  database=self.database, existing=bool(self.credentials))
                row = dict(schema='carrier/agent-launch-1', request_digest=digest, record=record,
                           records=str(self.root / 'threads'), thread_id=session['native_id'] if session else None,
                           source_ref=session['ref'] if session else None, status='pending', phase='prepared',
                           execution=dict(provider=self.manager.provider, config=str(self.manager.configuration_source),
                                          root=str(self.manager.root.parent), run_id=operation, environment_id=target.environment_id))
                if start_intent is not None: row['start_intent'] = start_intent
                if startup is not None: row['startup'] = startup
                atomic(path, row)
            await self._identity(row['record'])
            prepared = self._settings(path)
            user_config = options.pop('native_config', None) or {}
            if not isinstance(user_config, dict) or set(user_config).intersection(prepared):
                raise ValueError('Native configuration conflicts with Carrier settings')
            options['native_config'] = {**user_config, **prepared}
            with lease(path.with_suffix('.lock')):
                current = read(path)
                current['phase'] = 'submitting'
                current['record']['existing'] = True
                atomic(path, current)
            try:
                if session:
                    run = await self.agents.continue_session(session['ref'], profile=target,
                        idempotency_key=operation, **options)
                else:
                    run = await self.agents.spawn(profile=target, idempotency_key=operation, **options)
            except BaseException:
                # The SDK retains intent before process submission. After an
                # unwound failure, absent intent proves this operation did not launch.
                from agent_manager import RunNotFoundError
                try: await self.agents.execution_status(operation)
                except RunNotFoundError:
                    from .binding import close
                    close(path)
                except Exception: self._monitor(path)
                else: self._monitor(path)
                raise
            with lease(path.with_suffix('.lock')):
                current = read(path)
                current['phase'] = 'submitted'
                atomic(path, current)
            self._monitor(path)
            return run

    async def inspect(self, idempotency_key):
        """Read public launch and binding state without starting an execution."""
        operation = uuid.UUID(str(idempotency_key)).hex
        row = await asyncio.to_thread(read, self.root / 'operations' / (operation + '.json'))
        if row.get('schema') != 'carrier/agent-launch-1' or row['execution']['provider'] != self.manager.provider:
            raise ValueError('Carrier operation does not match this agent integration')
        from agent_manager import RunNotFoundError
        try:
            observation = await self.agents.execution_status(row['execution']['run_id'])
            state = observation['state']
        except RunNotFoundError:
            state = 'unknown'
        return dict(operation_id=operation, run_id=row['execution']['run_id'],
                    environment_id=row['execution']['environment_id'], address=row['record']['address'],
                    thread_id=row.get('thread_id'), status=row['status'], phase=row.get('phase'), state=state)

    async def adopt_legacy(self, session_id):
        """Explicitly adopt one inactive legacy association; never move credentials."""
        thread = str(uuid.UUID(session_id))
        source = self.manager.root / 'carrier' / 'threads' / (thread + '.json')
        destination = self.root / 'threads' / (thread + '.json')
        private_directory(self.root)
        async with async_lease(self.root / 'threads' / '.import.lock'):
            active = source.with_suffix('.active')
            if active.exists():
                launch = read(Path(read(active)))
                if launch.get('status') != 'closed':
                    managed = launch.get('managed_run')
                    if not managed or (await self.agents.execution_status(managed['run_id']))['state'] != 'terminated':
                        raise ValueError('Legacy Carrier run is active or unconfirmed; stop and inspect it before adoption')
            original = read(source)
            record = dict(address=original['address'], credentials=original['credentials'],
                          url=original['url'], database=original.get('db'), existing=True)
            await self._identity(record)
            with lease(self.root / 'threads' / '.lock'):
                if destination.exists() and read(destination) != record:
                    raise ValueError('Destination already has a different Carrier association')
                atomic(destination, record)
            return dict(session_id=thread, address=record['address'], source_preserved=True)

    async def reconcile(self):
        result = []
        for path in sorted((self.root / 'operations').glob('*.json')):
            row = read(path)
            if row['status'] in ('closed', 'blocked'): continue
            from agent_manager import RunNotFoundError
            try: observation = await self.agents.execution_status(row['execution']['run_id'])
            except RunNotFoundError:
                result.append(dict(run_id=row['execution']['run_id'], state='unknown'))
                if row.get('phase') in ('submitting', 'submitted'): self._monitor(path)
                continue
            if observation['state'] == 'terminated':
                from .binding import close
                await asyncio.to_thread(close, path)
            else: self._monitor(path)
            result.append(dict(run_id=row['execution']['run_id'], state=observation['state']))
        return result
