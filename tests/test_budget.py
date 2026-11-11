from aixand_filesystem import verify_private

import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import pytest

from carrier.service import Store, create_app


@pytest.fixture
def setup(tmp_path):
    path = str(tmp_path / 'carrier.db')
    store = Store(path)
    recipient = store.provision('operator')
    other = store.provision('other')
    source = store.provision_budget('source', 'operator')
    return path, store, TestClient(create_app(path)), recipient, other, source


def headers(token):
    return {'Authorization': 'Bearer ' + token}


def event(**changes):
    return dict(dict(event_id='event1', source_id='source', event='budget.threshold_crossed',
                     auth_profile='personal', observed_at=1000, window='weekly', bucket='default',
                     thresholds=[20, 10], remaining_percent=8, resets_at=2000), **changes)


def test_authenticated_ingestion_fixed_route_restart_and_ack(setup):
    path, store, client, recipient, other, source = setup
    assert client.post('/events/budget', json=event()).status_code == 401
    assert client.post('/events/budget', json=event(), headers=headers(recipient)).status_code == 403
    assert client.post('/events/budget', json=event(source_id='impersonated'), headers=headers(source)).status_code == 403
    response = client.post('/events/budget', json=event(), headers=headers(source))
    assert response.status_code == 200
    # Changing the source's ordinary selected recipient cannot reroute alerts.
    assert client.post('/connect', json={'to': 'other'}, headers=headers(source)).status_code == 200
    client = TestClient(create_app(path))
    assert client.get('/budget-source', headers=headers(source)).json() == {'address': 'source', 'recipient': 'operator'}
    assert client.post('/events/budget', json=event(), headers=headers(source)).json() == response.json()
    conflict = client.post('/events/budget', json=event(remaining_percent=7), headers=headers(source))
    assert conflict.status_code == 409
    inbox = client.get('/receive_pending', headers=headers(recipient)).json()['messages']
    assert len(inbox) == 1
    assert json.loads(inbox[0]['content'])['remaining_percent'] == 8
    assert client.get('/receive_pending', headers=headers(other)).json()['messages'] == []
    assert client.post('/ack', headers=headers(recipient), json={'message_id': inbox[0]['id']}).status_code == 200
    assert client.post('/events/budget', json=event(), headers=headers(source)).status_code == 200
    assert client.get('/receive_pending', headers=headers(recipient)).json()['messages'] == []
    assert client.post('/events/budget', json=event(event_id='event2'), headers=headers(source)).status_code == 200
    assert len(client.get('/receive_pending', headers=headers(recipient)).json()['messages']) == 1


def test_validation_and_explicit_test_event(setup):
    _, _, client, recipient, _, source = setup
    for changes in ({'remaining_percent': 101}, {'thresholds': [-1]}, {'thresholds': [5]},
                    {'window': None}, {'test': True}, {'unexpected': 'field'}):
        assert client.post('/events/budget', json=event(**changes), headers=headers(source)).status_code == 422
    test = dict(event='budget.test', event_id='test1', source_id='source', auth_profile='personal', observed_at=1, test=True)
    assert client.post('/events/budget', json=test, headers=headers(source)).status_code == 200
    messages = client.get('/receive_pending', headers=headers(recipient)).json()['messages']
    assert json.loads(messages[0]['content'])['test'] is True


def test_transaction_rolls_back_and_concurrent_retries_store_once(setup):
    _, store, client, recipient, _, source = setup
    with store.db() as db:
        db.execute("CREATE TRIGGER fail_event BEFORE INSERT ON budget_events BEGIN SELECT RAISE(ABORT, 'test'); END")
    with pytest.raises(sqlite3.IntegrityError):
        client.post('/events/budget', json=event(), headers=headers(source))
    with store.db() as db:
        assert db.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM budget_events').fetchone()[0] == 0
        db.execute('DROP TRIGGER fail_event')
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda _: client.post('/events/budget', json=event(), headers=headers(source)), range(8)))
    assert all(reply.status_code == 200 for reply in replies)
    assert len({reply.json()['message_id'] for reply in replies}) == 1
    assert len(client.get('/receive_pending', headers=headers(recipient)).json()['messages']) == 1


def test_cli_provisions_private_identity_and_rejects_missing_recipient(tmp_path):
    path = str(tmp_path / 'db')
    store = Store(path)
    store.provision('operator')
    credentials = tmp_path / 'source.json'
    args = [sys.executable, '-m', 'carrier.cli', 'budget-source', 'source', '--to', 'missing',
            '--db', path, '--credentials', str(credentials)]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode != 0
    assert not credentials.exists()
    args[args.index('missing')] = 'operator'
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    verify_private(credentials)
    token = json.loads(credentials.read_text())['token']
    assert token not in result.stdout
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode != 0
    assert json.loads(credentials.read_text())['token'] == token


def test_agent_manager_default_destination_over_http(tmp_path, monkeypatch):
    # Optional sibling checkout integration; standalone Carrier tests need no manager dependency.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'manager-suites/agent-manager'))
    watch = pytest.importorskip('agent_manager.watch')
    from agent_manager.core import Manager
    from agent_manager.cli import parser
    import uvicorn

    path = str(tmp_path / 'carrier.db')
    store = Store(path)
    recipient_token = store.provision('operator')
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    url = f'http://127.0.0.1:{sock.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(create_app(path), log_level='error'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        manager = Manager('codex', root=str(tmp_path / 'managed'))
        manager.save({'agents': {'default': None}, 'auths': ['personal']})
        manager.config['carrier'] = dict(command=str(Path(sys.executable).parent / 'carrier'),
                                         db=path, url=url, budget_recipient='operator')
        args = parser().parse_args(['codex', 'budget', 'watch', 'configure', '--profile', 'personal'])
        watch.configure(manager, args)
        config = watch.settings(manager)['personal']
        assert config['webhook'] == url + '/events/budget'
        watch.check_carrier_health(manager, {'personal': config})
        source_id = config['source_id']
        watch.configure(manager, args)
        assert watch.settings(manager)['personal']['source_id'] == source_id
        # Re-selecting Carrier validates and reuses the durable service identity.
        args.carrier = True
        watch.configure(manager, args)
        assert watch.settings(manager)['personal']['source_id'] == source_id
        payload = event(source_id=source_id)
        watch.deliver(config, payload)
        watch.deliver(config, payload)
        client = TestClient(create_app(path))
        messages = client.get('/receive_pending', headers=headers(recipient_token)).json()['messages']
        assert len(messages) == 1
        assert json.loads(messages[0]['content'])['source_id'] == source_id
        assert source_id.startswith('budget-')
        assert json.loads(Path(config['carrier_credentials']).read_text())['token'] not in json.dumps(config)
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()
