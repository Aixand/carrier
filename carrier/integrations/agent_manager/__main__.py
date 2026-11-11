"""Detached binding monitor. No process launch, stop or identity provisioning."""
import argparse
from pathlib import Path
import time
from aixand_filesystem import lock_file, private_path
from .binding import close, execution_state
from .storage import read


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['monitor'])
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    with args.path.with_suffix('.monitor.lock').open('a') as owner:
        private_path(owner.name)
        try: lock_file(owner, blocking=False)
        except BlockingIOError: return
        while read(args.path)['status'] not in ('closed', 'blocked'):
            try:
                if execution_state(args.path) == 'terminated':
                    close(args.path)
                    return
            except (OSError, ValueError): pass
            time.sleep(1)


if __name__ == '__main__': main()
