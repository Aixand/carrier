"""Optional agent adapter: real local Carrier store/HTTP, fake process runtime."""
import asyncio
from contextlib import contextmanager
import importlib.util
import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import uuid

import httpx
import pytest

from carrier.integrations.agent_manager import CarrierAgents
from carrier.integrations.agent_manager import binding
from carrier.integrations.agent_manager.storage import atomic, read
from carrier.service import create_app

agent_available = importlib.util.find_spec('agent_manager') is not None
pytestmark = pytest.mark.skipif(not agent_available, reason='Requires the optional Agent Manager source/extra')


@contextmanager
def fixture(root):
    from agent_manager import Client, Manager
    from agent_manager.runtime.runs import update_run
    config = root / 'providers.toml'
    config.write_text('')
    manager = Manager('codex', config=config, root=root / 'agents')
    manager.new_profile('main')
    manager.set_default('main')
    runtime = SimpleNamespace(connection_options={'home': str(root / 'runtime')}, connect=AsyncMock())
    agents = Client('codex', config=config, root=root / 'agents', runtime=runtime)
    agents.reconcile = AsyncMock()
    database = root / 'carrier.db'
    transport = httpx.ASGITransport(app=create_app(str(database)))
    def accepted(owner, run_id): update_run(owner, run_id, session_id='runtime-' + run_id, status='running')
    adapter = CarrierAgents(agents, database=database, home=root / 'adapter', monitor=False, transport=transport)
    with patch('agent_manager.interfaces.sdk.launch_worker', side_effect=accepted):
        yield adapter, agents, manager


def test_fresh_launch_retry_and_secret_boundaries(tmp_path):
    async def exercise():
        from agent_manager.runtime.runs import read_run
        with fixture(tmp_path) as (adapter, agents, manager):
            key = str(uuid.uuid4())
            first = await adapter.spawn(profile='main', idempotency_key=key, cwd=tmp_path)
            second = await adapter.spawn(profile='main', idempotency_key=key, cwd=tmp_path)
            assert first.run_id == second.run_id
            path = next((adapter.root / 'operations').glob('*.json'))
            row = read(path)
            token = read(row['record']['credentials'])['token']
            assert token not in path.read_text()
            core = read_run(manager, first.run_id)
            assert 'carrier_launch' not in core
            assert core['environment_id'] == row['execution']['environment_id']
            command = core['launch']['command']
            assert any('mcp_servers.carrier.command=' in item for item in command)
            assert token not in json.dumps(core)
            with pytest.raises(ValueError, match='different launch intent'):
                await adapter.spawn(profile='main', idempotency_key=key, cwd=tmp_path, model='different')
    asyncio.run(exercise())


def test_binding_retains_identity_and_unknown_lease(tmp_path):
    async def exercise():
        from agent_manager import Manager
        with fixture(tmp_path) as (adapter, agents, manager):
            await adapter.spawn(profile='main', cwd=tmp_path)
            path = next((adapter.root / 'operations').glob('*.json'))
            row = read(path)
            thread = str(uuid.uuid4())
            event = dict(session_id=thread, hook_event_name='SessionStart')
            with patch.object(Manager, 'execution_status', return_value=dict(state='active', environment_id=row['execution']['environment_id'])):
                address = await asyncio.to_thread(binding.bind, path, event)
                assert address == row['record']['address']
                assert read(path)['status'] == 'bound'
            with patch.object(Manager, 'execution_status', return_value=dict(state='unknown', environment_id=row['execution']['environment_id'])):
                assert await asyncio.to_thread(binding.is_active, path)
                with pytest.raises(ValueError, match='confirmed active'):
                    await asyncio.to_thread(binding.bind, path, event)
                assert read(path)['status'] == 'bound'
            with patch.object(Manager, 'execution_status', return_value=dict(state='active', environment_id=row['execution']['environment_id'])):
                with pytest.raises(ValueError, match='conversation changed'):
                    await asyncio.to_thread(binding.bind, path, dict(event, session_id=str(uuid.uuid4())))
                assert read(path)['status'] == 'blocked'
    asyncio.run(exercise())


def test_monitor_closes_only_after_observed_termination(tmp_path):
    async def exercise():
        from agent_manager.runtime.runs import finish_run
        with fixture(tmp_path) as (adapter, agents, manager):
            run = await adapter.spawn(profile='main', cwd=tmp_path)
            path = next((adapter.root / 'operations').glob('*.json'))
            agents.execution_status = AsyncMock(return_value={'state': 'unknown'})
            assert (await adapter.reconcile())[0]['state'] == 'unknown'
            assert read(path)['status'] == 'pending'
            finish_run(manager, run.run_id, status='finished')
            # A separate interpreter proves cleanup outlives the SDK handle.
            result = await asyncio.to_thread(subprocess.run,
                [sys.executable, '-m', 'carrier.integrations.agent_manager', 'monitor', str(path)],
                capture_output=True, text=True, timeout=15)
            assert result.returncode == 0, result.stderr
            assert read(path)['status'] == 'closed'
    asyncio.run(exercise())


def test_continuation_uses_original_carrier_identity_and_native_settings(tmp_path):
    async def exercise():
        from agent_manager import Manager
        from agent_manager.profiles.sessions import remember
        from agent_manager.runtime.runs import finish_run, read_run
        with fixture(tmp_path) as (adapter, agents, manager):
            run = await adapter.spawn(profile='main', cwd=tmp_path)
            path = next((adapter.root / 'operations').glob('*.json'))
            row = read(path)
            thread = str(uuid.uuid4())
            with patch.object(Manager, 'execution_status', return_value=dict(state='active', environment_id=row['execution']['environment_id'])):
                await asyncio.to_thread(binding.bind, path, dict(session_id=thread, hook_event_name='SessionStart'))
            history = manager.home('main') / 'sessions'
            history.mkdir(exist_ok=True)
            (history / 'rollout.jsonl').write_text(json.dumps({'type': 'session_meta', 'payload': {'id': thread, 'cwd': str(tmp_path)}}) + '\n')
            saved = remember(manager, 'main', thread, cwd=tmp_path)
            finish_run(manager, run.run_id, status='finished')
            resumed = await adapter.continue_session(saved['ref'], profile='main')
            rows = [read(p) for p in (adapter.root / 'operations').glob('*.json')]
            assert {item['record']['address'] for item in rows} == {row['record']['address']}
            assert read_run(manager, resumed.run_id)['launch']['command'][-2:] == ['resume', thread]
    asyncio.run(exercise())


def test_concurrent_same_key_launches_once(tmp_path):
    async def exercise():
        with fixture(tmp_path) as (adapter, agents, manager):
            key = str(uuid.uuid4())
            first, second = await asyncio.gather(
                adapter.spawn(profile='main', idempotency_key=key, cwd=tmp_path),
                adapter.spawn(profile='main', idempotency_key=key, cwd=tmp_path))
            assert first.run_id == second.run_id
            assert len(manager.state()['runs']) == 1
            assert len(list((adapter.root / 'operations').glob('*.json'))) == 1
    asyncio.run(exercise())


def test_import_adopts_original_credentials_without_deleting_legacy_data(tmp_path):
    async def exercise():
        with fixture(tmp_path) as (adapter, agents, manager):
            await adapter.spawn(profile='main', cwd=tmp_path)
            row = read(next((adapter.root / 'operations').glob('*.json')))
            thread = str(uuid.uuid4())
            source = manager.root / 'carrier' / 'threads' / (thread + '.json')
            original = row['record']
            atomic(source, dict(address=original['address'], credentials=original['credentials'],
                                url=original['url'], db=original['database'], command='carrier'))
            before = source.read_bytes()
            imported = await adapter.adopt_legacy(thread)
            assert imported['address'] == original['address']
            assert source.read_bytes() == before
            assert read(adapter.root / 'threads' / (thread + '.json'))['credentials'] == original['credentials']
    asyncio.run(exercise())


def test_invalid_targets_and_remote_provisioning_fail_before_any_journal(tmp_path):
    with fixture(tmp_path) as (adapter, agents, manager):
        with pytest.raises(ValueError, match='local Carrier service'):
            CarrierAgents(agents, url='https://example.invalid', database=tmp_path / 'db')
        with pytest.raises(TypeError): asyncio.run(adapter.spawn(profile='main', unknown_setting=True))
        assert not adapter.root.exists()


def test_offline_service_does_not_provision_identity(tmp_path):
    async def exercise():
        with fixture(tmp_path) as (adapter, agents, manager):
            adapter._transport = httpx.MockTransport(lambda request: httpx.Response(503))
            with pytest.raises(ValueError, match='unavailable or unhealthy'):
                await adapter.spawn(profile='main', cwd=tmp_path)
            assert not list((adapter.root / 'credentials').glob('*.json'))
            assert not manager.state()['runs']
    asyncio.run(exercise())


def test_start_retry_recovers_original_environment_without_reselection(tmp_path):
    async def exercise():
        from agent_manager.profiles.operations import inspect_profile
        with fixture(tmp_path) as (adapter, agents, manager):
            selected = inspect_profile(manager, 'main')
            selected['selection'] = {'model': None}
            agents.select_profile = AsyncMock(return_value=selected)
            key = str(uuid.uuid4())
            first = await adapter.start(idempotency_key=key, cwd=tmp_path)
            manager.rename('main', 'renamed')
            manager.new_profile('main')
            agents.select_profile.side_effect = AssertionError('A retry must not select a new environment')
            second = await adapter.start(idempotency_key=key, cwd=tmp_path)
            assert first.run_id == second.run_id
            assert second.environment_id == first.environment_id
            with pytest.raises(ValueError, match='different startup intent'):
                await adapter.start(idempotency_key=key, cwd=tmp_path, model='different')
    asyncio.run(exercise())


def test_cancellation_retains_uncertain_binding_and_original_run(tmp_path):
    async def exercise():
        from agent_manager.runtime.runs import read_run
        with fixture(tmp_path) as (adapter, agents, manager):
            spawn = agents.spawn
            async def cancelled(**options):
                await spawn(**options)
                raise asyncio.CancelledError()
            agents.spawn = cancelled
            agents.execution_status = AsyncMock(return_value={'state': 'unknown'})
            key = str(uuid.uuid4())
            with pytest.raises(asyncio.CancelledError):
                await adapter.spawn(profile='main', cwd=tmp_path, idempotency_key=key)
            row = read(next((adapter.root / 'operations').glob('*.json')))
            assert row['status'] == 'pending'
            assert read_run(manager, uuid.UUID(key).hex)['status'] == 'running'
            agents.spawn = spawn
            same = await adapter.spawn(profile='main', cwd=tmp_path, idempotency_key=key)
            assert same.run_id == uuid.UUID(key).hex
    asyncio.run(exercise())


def test_native_conflicts_fail_before_provisioning_including_quoted_parent_keys(tmp_path):
    with fixture(tmp_path) as (adapter, agents, manager):
        for native_config in ({'hooks': {}}, {'"mcp_servers"': {}}, {'mcp_servers.carrier.command': 'wrong'}, {'key': None}):
            with pytest.raises(ValueError):
                asyncio.run(adapter.spawn(profile='main', native_config=native_config))
        assert not adapter.root.exists()


def test_base_cli_has_no_agent_manager_import_requirement(tmp_path):
    script = '''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'agent_manager': raise AssertionError('Unexpected Agent Manager import')
sys.meta_path.insert(0, Block())
from carrier.cli import main
sys.argv = ['carrier', '--help']
main()
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'agent' in result.stdout


def test_start_recovers_prelaunch_health_failure_without_reselecting_or_retargeting(tmp_path):
    async def exercise():
        from agent_manager.profiles.operations import inspect_profile
        with fixture(tmp_path) as (adapter, agents, manager):
            selected = inspect_profile(manager, 'main')
            selected['selection'] = {'model': None}
            agents.select_profile = AsyncMock(return_value=selected)
            healthy = adapter._transport
            adapter._transport = httpx.MockTransport(lambda request: httpx.Response(503))
            key = str(uuid.uuid4())
            with pytest.raises(ValueError, match='unavailable or unhealthy'):
                await adapter.start(idempotency_key=key, cwd=tmp_path)
            manager.rename('main', 'renamed')
            manager.new_profile('main')
            agents.select_profile.side_effect = AssertionError('Must retain the original selected environment')
            adapter._transport = healthy
            recovered = await adapter.start(idempotency_key=key, cwd=tmp_path)
            assert recovered.environment_id == selected['environment_id']
            assert recovered.run_id == uuid.UUID(key).hex
    asyncio.run(exercise())


def test_public_inspection_keeps_credentials_private_and_does_not_launch(tmp_path):
    async def run():
        with fixture(tmp_path) as (adapter, agents, manager):
            operation = str(uuid.uuid4())
            agent = await adapter.spawn(profile='main', idempotency_key=operation, cwd=str(tmp_path))
            agents.execution_status = AsyncMock(return_value={'state': 'active'})
            with patch.object(agents, 'spawn') as launch:
                result = await adapter.inspect(operation)
            launch.assert_not_called()
            assert result['run_id'] == agent.run_id
            assert result['state'] == 'active'
            assert result['address']
            assert 'credentials' not in json.dumps(result)
            assert 'token' not in json.dumps(result)
            assert 'database' not in result
    asyncio.run(run())


def test_public_inspection_retains_unknown_execution_without_replay(tmp_path):
    async def run():
        from agent_manager import RunNotFoundError
        with fixture(tmp_path) as (adapter, agents, manager):
            operation = str(uuid.uuid4())
            agent = await adapter.spawn(profile='main', idempotency_key=operation, cwd=str(tmp_path))
            agents.execution_status = AsyncMock(side_effect=RunNotFoundError('missing'))
            result = await adapter.inspect(operation)
            assert result['run_id'] == agent.run_id
            assert result['state'] == 'unknown'
    asyncio.run(run())
