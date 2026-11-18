"""Verify documented workflows using isolated loopback services and real manager APIs.

Run from the Carrier checkout in the SDK environment with the four optional
Manager Suite packages installed. No model account or native agent is used.
Evidence is retained in the printed temporary directory.
"""
import asyncio,json,os,socket,sqlite3,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
from carrier import Client,ensure_session
source=Path(__file__).resolve().parents[1]
stage=source
root=Path(tempfile.mkdtemp(prefix='carrier-doc-check-'))
python=sys.executable
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
url=f'http://127.0.0.1:{port}'
for name,address in [('requester','sdk/requester'),('worker','sdk/report-worker'),('events','sdk/build-events')]:
 ensure_session(database=root/'carrier.db',credentials=root/f'{name}.json',address=address)
log=(root/'service.log').open('w')
service=None;worker=None

def start():
 global service
 service=subprocess.Popen([python,'-m','carrier','serve','--db',str(root/'carrier.db'),'--port',str(port)],cwd=root,env=env,stdout=log,stderr=log)
 for _ in range(100):
  try:
   with urllib.request.urlopen(url+'/health',timeout=.2):return
  except Exception:time.sleep(.05)
 raise RuntimeError('Service did not start')
def run(script,*args,ok=True):
 result=subprocess.run([python,str(stage/'examples'/script),*map(str,args)],cwd=root,env=env,text=True,capture_output=True,timeout=60)
 if ok and result.returncode:raise RuntimeError(f'{script}: {result.stdout}\n{result.stderr}')
 return result

def handoff(kind,action='prepare'):
 args=[action,'--work',root/kind,'--url',url,'--credentials',root/'requester.json']
 if action=='prepare':args+=['--kind',kind,'--task-id',kind+'-001','--adapter-credentials',root/'events.json']
 return json.loads(run('manager_handoff.py',*args).stdout)
def archive():
 return run('archive_events.py','--url',url,'--credentials',root/'events.json','--archive',root/'archive.db','--page-size','2').stdout

async def confirm():
 async with Client(url=url,credentials=root/'events.json') as inbox:
  assert not (await inbox.receive_pending()).messages
  rows=(await inbox.receive()).messages
  assert len(rows)==4
  bodies={row.json()['type']:row.json() for row in rows}
  assert bodies['manager.prompt']['result']['messages'][0]['content']=='Review the report and check its totals.'
  assert bodies['manager.skill']['result']['report']=={'total':150}
  assert bodies['manager.mcp']['result']['server_started'] is False
  assert bodies['manager.conversation']['result']['provider']=='injected-fixture'
 with sqlite3.connect(root/'archive.db') as db:assert db.execute('SELECT count(*) FROM events').fetchone()[0]==4

try:
 start()
 originals={kind:handoff(kind) for kind in ['prompt','skill','mcp','conversation']}
 assert all(row['status']=='stored' for row in originals.values())
 assert all(handoff(kind,'retry')['message_id']==row['message_id'] for kind,row in originals.items())
 assert 'Accepted 4 pending' in archive()
 assert 'Accepted 0 pending' in archive()
 assert all(handoff(kind,'retry')['status']=='acknowledged' for kind in originals)
 asyncio.run(confirm())
 print('PASS: all four manager APIs, saved-intent retries, two-message pagination, commit-before-ack, payload assertions and empty rerun',flush=True)
 # A service restart keeps the same credentials and acknowledged IDs.
 service.terminate();service.wait(timeout=10);start()
 assert all(handoff(kind,'retry')['message_id']==row['message_id'] for kind,row in originals.items())
 print('PASS: service restart preserves all handoff identities, history and retry receipts',flush=True)
 # Original report scripts execute as separate real processes.
 worker=subprocess.Popen([python,str(stage/'examples/report_worker.py'),'--url',url,'--credentials',str(root/'worker.json')],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=log)
 report=run('request_report.py','--url',url,'--credentials',root/'requester.json','--timeout','10')
 assert json.loads(report.stdout)['failed']==['integration']
 print('PASS: CI worker request, correlated report and acknowledgments',flush=True)
 first=run('publish_build_event.py','build-1842','--url',url,'--credentials',root/'requester.json')
 second=run('publish_build_event.py','build-1842','--url',url,'--credentials',root/'requester.json')
 assert first.stdout==second.stdout
 conflict=run('publish_build_event.py','build-1842','--status','failed','--url',url,'--credentials',root/'requester.json',ok=False)
 assert conflict.returncode!=0
 assert 'Accepted 1 pending' in archive()
 assert 'acknowledged' in run('publish_build_event.py','build-1842','--url',url,'--credentials',root/'requester.json').stdout
 print('PASS: stable build event, changed-payload conflict, offline archive and acknowledged retry',flush=True)
 print('Evidence:',root,flush=True)
finally:
 if worker:
  worker.terminate();worker.wait(timeout=10)
 if service:
  service.terminate();service.wait(timeout=10)
 log.close()
