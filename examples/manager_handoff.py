"""Prepare real Manager Suite resources, save a delivery intent, and send it.

No model is called. Each prepare action requires a fresh work directory.
Retry reuses its saved bytes and Carrier retry key without running managers again.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from carrier import Client


def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def prepare_prompt(root):
    from prompt_manager import Manager
    manager = Manager(home=root / 'prompts', packs=[])
    manager.create_managed('review', content='Review the report and check its totals.', role='user')
    result = manager.render_managed('local', 'review', 'review', format='messages')
    messages = result['output']
    assert messages == [{'role': 'user', 'content': 'Review the report and check its totals.'}]
    return {'messages': messages, 'model_called': False}


def prepare_skill(root):
    from skill_manager import Manager
    publisher = root / 'publisher' / 'total'
    (publisher / 'scripts').mkdir(parents=True)
    (publisher / 'SKILL.md').write_text(
        '---\nname: total\ndescription: Sum a fixed list of integer amounts.\n---\n'
        'Run scripts/total.py with a JSON input path.\n')
    (publisher / 'scripts' / 'total.py').write_text(
        'import json,sys\nfrom pathlib import Path\n'
        'values=json.loads(Path(sys.argv[1]).read_text())\n'
        'print(json.dumps({"total": sum(values)}))\n')
    manager = Manager(root / 'skills')
    skill = manager.skill('carrier-demo', 'total')
    skill.register(publisher, publisher_revision=1)
    project = root / 'project'
    project.mkdir()
    selected = manager.project(project)
    plan = selected.preview_connect([skill.reference], skills_dir='skills')
    selected.connect(plan)
    executable = project / 'skills' / 'total' / 'scripts' / 'total.py'
    data = project / 'amounts.json'
    data.write_text('[120, 55, -25]\n')
    # The application explicitly runs this trusted fixture; Skill Manager does not.
    process = subprocess.run([sys.executable, str(executable), str(data)], cwd=project,
                             check=True, capture_output=True, text=True, timeout=10)
    result = json.loads(process.stdout)
    assert result == {'total': 150}
    save(root / 'result.json', result)
    return {'report': result, 'script_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'application_executed_script': True}


def prepare_mcp(root, args):
    from mcp_manager import Manager
    executable = str(Path(sys.executable).resolve())
    credential_path = str(Path(args.adapter_credentials).resolve())
    manager = Manager(home=root / 'mcp')
    created = manager.add('carrier', {'command': executable, 'args': [
        '-m', 'carrier', 'mcp', '--url', args.url, '--credentials', credential_path]})
    manager.configure('carrier', {'tool_timeout_sec': 90}, expected_revision=created['revision'])
    resolved = manager.resolve(['carrier'], str(root), project=None, check=False)
    definition = resolved['servers']['carrier']
    assert definition['tool_timeout_sec'] == 90
    save(root / 'resolved.json', resolved)
    # The handoff announces the selected definition, without exporting private paths.
    return {'selected': ['carrier'], 'tool_timeout_sec': definition['tool_timeout_sec'],
            'server_started': False, 'connection_verified': False}


async def prepare_conversation(root):
    from conversation_manager.demo import demo
    result = await demo()
    assert result['status'] == 'completed' and result['reattached_same_runtime'] is True
    assert any(event['kind'] == 'turn.completed' for event in result['events'])
    evidence = {'status': result['status'], 'reattached_same_runtime': True,
                'turn_completed': True, 'provider': 'injected-fixture'}
    save(root / 'conversation-result.json', evidence)
    return evidence


async def main(args):
    root = args.work.resolve()
    if args.action == 'prepare':
        root.mkdir(parents=True, exist_ok=False, mode=0o700)
        if args.kind == 'prompt': value = prepare_prompt(root)
        elif args.kind == 'skill': value = prepare_skill(root)
        elif args.kind == 'mcp': value = prepare_mcp(root, args)
        else: value = await prepare_conversation(root)
        body = json.dumps({'type': f'manager.{args.kind}', 'task_id': args.task_id, 'result': value}, sort_keys=True, allow_nan=False)
        # Save the exact routing, bytes and retry key before any network mutation.
        intent = {'to': args.to, 'content': body,
                  'idempotency_key': 'manager:' + hashlib.sha256(body.encode()).hexdigest()}
        save(root / 'delivery.json', intent)
    else:
        intent = json.loads((root / 'delivery.json').read_text())
    async with Client(url=args.url, credentials=args.credentials) as inbox:
        message = await inbox.send(**intent)
        status = await inbox.delivery_status(intent['idempotency_key'])
        print(json.dumps({'message_id': message.id, 'status': status['status'],
                          'kind': json.loads(intent['content'])['type']}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'retry'])
    parser.add_argument('--task-id', help='Stable application task identity')
    parser.add_argument('--kind', choices=['prompt', 'skill', 'mcp', 'conversation'])
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--url', default='http://127.0.0.1:8877')
    parser.add_argument('--credentials', default='.carrier/sdk/requester.json')
    parser.add_argument('--to', default='sdk/build-events')
    parser.add_argument('--adapter-credentials', default='.carrier/sdk/events.json')
    args = parser.parse_args()
    if args.action == 'prepare' and (not args.kind or not args.task_id):
        parser.error('prepare requires --kind and --task-id')
    asyncio.run(main(args))
