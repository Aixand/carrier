"""Isolated Carrier + Undercurrent qualification; fake native CLI, no model/login."""
import asyncio
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import uvicorn
import undercurrent
from agent_manager import Client, Manager
from carrier.integrations.agent_manager import CarrierAgents
from carrier.service import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-bin', required=True, type=Path, help='Directory containing uc-daemon and uc-python-bridge')
    binaries = parser.parse_args().runtime_bin.resolve()
    for name in ('uc-daemon', 'uc-python-bridge'):
        if not (binaries / name).is_file(): parser.error('Missing runtime executable: ' + name)
    with tempfile.TemporaryDirectory(prefix='carrier-agent-qualification-') as temporary:
        root = Path(temporary)
        runtime_home = root / 'runtime'
        runtime_home.mkdir(mode=0o700)
        database = root / 'carrier.db'
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(str(database)), log_level='error'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        log = (root / 'daemon.log').open('wb')
        daemon = subprocess.Popen([str(binaries / 'uc-daemon')], env=os.environ | {'UNDERCURRENT_HOME': str(runtime_home)},
                                  stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 15
            while not (runtime_home / 'run/control.sock').exists() or not server.started:
                if daemon.poll() is not None: raise RuntimeError('Isolated Undercurrent daemon exited')
                if time.monotonic() > deadline: raise TimeoutError('Isolated services did not become ready')
                time.sleep(.05)
            program = root / 'native-fixture'
            release = root / 'release'
            result = root / 'binding-result.json'
            program.write_text('#!' + sys.executable + '\n' + '''
import json,os,subprocess,sys,time,tomllib,uuid
from pathlib import Path
args=sys.argv[1:]
settings={}
for i,item in enumerate(args):
    if item=='-c':
        row=tomllib.loads(args[i+1])
        if 'mcp_servers' in row:
            settings.update(row['mcp_servers'].get('carrier',{}))
carrier_args=settings['args']
binding=carrier_args[carrier_args.index('--binding')+1]
hook=carrier_args[carrier_args.index('--binding-hook')+1]
event=json.dumps({'session_id':str(uuid.uuid4()),'hook_event_name':'SessionStart'})
for attempt in range(30):
    response=subprocess.run([sys.executable,hook,binding],input=event,text=True,capture_output=True)
    if response.returncode==0:break
    time.sleep(.1)
else:raise RuntimeError('Carrier binding failed: '+response.stdout)
Path(RESULT).write_text(response.stdout)
for attempt in range(300):
    if Path(RELEASE).exists():break
    time.sleep(.1)
'''.replace('RESULT', repr(str(result))).replace('RELEASE', repr(str(release))))
            program.chmod(0o700)
            config = root / 'providers.toml'
            config.write_text('[providers.codex]\nexecutable=' + json.dumps(str(program)) + '\n')
            manager = Manager('codex', config=config, root=root / 'agents')
            manager.new_profile('main')
            async def exercise():
                runtime = undercurrent.Client(home=runtime_home, bridge=str(binaries / 'uc-python-bridge'), request_timeout=30)
                await runtime.connect()
                options = dict(profile='main', cwd=str(root), env={'PYTHONPATH': os.pathsep.join(sys.path)}, detection=False,
                               idempotency_key=str(uuid.uuid4()))
                try:
                    client = Client('codex', config=config, root=root / 'agents', runtime=runtime)
                    adapter = CarrierAgents(client, database=database, url=f'http://127.0.0.1:{port}', home=root / 'adapter')
                    run = await adapter.spawn(**options)
                    async with asyncio.timeout(15):
                        while not result.exists(): await asyncio.sleep(.1)
                    assert 'Carrier address' in result.read_text()
                    path = next((adapter.root / 'operations').glob('*.json'))
                    assert json.loads(path.read_text())['status'] == 'bound'
                    await client.close()
                    await runtime.close()
                    assert json.loads(path.read_text())['status'] == 'bound', 'SDK detach closed Carrier'
                    runtime = undercurrent.Client(home=runtime_home, bridge=str(binaries / 'uc-python-bridge'), request_timeout=30)
                    await runtime.connect()
                    client = Client('codex', config=config, root=root / 'agents', runtime=runtime)
                    adapter = CarrierAgents(client, database=database, url=f'http://127.0.0.1:{port}', home=root / 'adapter')
                    recovered = await adapter.spawn(**options)
                    assert recovered.run_id == run.run_id
                    assert (await client.execution_status(run.run_id))['state'] == 'active'
                    release.write_text('finish')
                    await runtime.wait(run.session_id, lifecycle=('stopped', 'exited', 'failed'), timeout=15)
                    async with asyncio.timeout(15):
                        while json.loads(path.read_text())['status'] != 'closed': await asyncio.sleep(.1)
                    assert (await client.execution_status(run.run_id))['state'] == 'terminated'
                    async with asyncio.timeout(15):
                        while await client.runs(include_finished=False): await asyncio.sleep(.1)
                    print('PASS: real isolated Undercurrent + Carrier HTTP; native hook binding, SDK detach/reconnect, keyed recovery and detached termination cleanup. No real provider/model/login.')
                finally:
                    for session in await runtime.list():
                        if session.lifecycle not in ('stopped','exited','failed'):
                            await runtime.stop(session, force=True)
                    await runtime.close()
            asyncio.run(exercise())
        finally:
            daemon.terminate()
            try: daemon.wait(timeout=10)
            except subprocess.TimeoutExpired:
                daemon.kill(); daemon.wait()
            log.close()
            server.should_exit = True
            thread.join(timeout=5)
            sock.close()


if __name__ == '__main__': main()
