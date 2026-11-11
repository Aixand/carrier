"""Carrier-owned conversation binding using public Agent Manager observations."""
import json
from pathlib import Path
import sys
import uuid

from carrier.integrations.agent_manager.storage import atomic, lease, read


def execution_state(path):
    row = read(path)
    if row['status'] in ('closed', 'blocked'): return 'terminated'
    from agent_manager import Manager, Error
    execution = row['execution']
    try:
        result = Manager(execution['provider'], config=execution['config'], root=execution['root']).execution_status(execution['run_id'])
        if result['environment_id'] != execution['environment_id']: return 'unknown'
        return result['state']
    except (Error, OSError, ValueError, RuntimeError):
        return 'unknown'


def is_active(path):
    # Unknown retains exclusive ownership. It does not authorize tool use.
    return execution_state(path) != 'terminated'


def close(path):
    path = Path(path)
    with lease(path.with_suffix('.lock')):
        row = read(path)
        row['status'] = 'closed'
        atomic(path, row)


def bind(path, event):
    path = Path(path)
    with lease(path.with_suffix('.lock')):
        row = read(path)
        try:
            if event.get('hook_event_name') not in ('SessionStart', 'PreToolUse', 'UserPromptSubmit', 'Stop'):
                raise ValueError('Expected a Carrier lifecycle hook')
            thread = str(uuid.UUID(event['session_id']))
            if row['status'] in ('closed', 'blocked'):
                raise ValueError('Carrier binding is closed or blocked')
            if row.get('thread_id') not in (None, thread):
                raise ValueError('The native conversation changed; start a separate Carrier launch')
            if execution_state(path) != 'active':
                raise ValueError('Execution could not be confirmed active; retain the binding and inspect the run')
            folder = Path(row['records'])
            target = folder / (thread + '.json')
            with lease(folder / '.lock'):
                active = target.with_suffix('.active')
                if active.exists():
                    other = Path(read(active))
                    if other != path and is_active(other):
                        raise ValueError('This conversation already has an active or unconfirmed Carrier run')
                if target.exists() and read(target) != row['record']:
                    raise ValueError('Conversation already has a different Carrier identity')
                atomic(target, row['record'])
                atomic(active, str(path))
            row.update(thread_id=thread, status='bound')
            atomic(path, row)
            return row['record']['address']
        except Exception:
            # Invalid conversation identity cannot continue using tools bound to
            # another thread. A transient execution observation retains its lease.
            if event.get('session_id') != row.get('thread_id') and row.get('thread_id') is not None:
                row['status'] = 'blocked'
                atomic(path, row)
            raise


def main():
    try:
        event = json.load(sys.stdin)
        address = bind(sys.argv[1], event)
        output = {'hookSpecificOutput': {'hookEventName': 'SessionStart',
                  'additionalContext': f'Carrier address for this conversation: {address}.'}} if event['hook_event_name'] == 'SessionStart' else {}
        print(json.dumps(output))
    except Exception as error:
        print(json.dumps({'continue': False, 'stopReason': f'Carrier binding failed: {error}'}))
        raise SystemExit(1)


if __name__ == '__main__': main()
