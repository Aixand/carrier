"""Recover pending inbox messages by archiving each one before acknowledging it."""

import argparse
import asyncio
from pathlib import Path
import sqlite3

from carrier import Client


async def main(args):
    path = Path(args.archive)
    path.parent.mkdir(parents=True, exist_ok=True)
    archive = sqlite3.connect(path)
    try:
        with archive:
            archive.execute("""CREATE TABLE IF NOT EXISTS events (
                backend TEXT NOT NULL,
                inbox TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (backend, inbox, message_id)
            )""")
        async with Client(url=args.url, credentials=args.credentials) as inbox:
            # The cursor lasts only for this scan. Every invocation starts at zero.
            after = 0
            accepted = 0
            while True:
                page = await inbox.receive_pending(after=after, limit=args.page_size)
                for message in page.messages:
                    # Commit before ack: a crash in between reuses the saved row.
                    with archive:
                        archive.execute(
                            "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?)",
                            (inbox.url, inbox.address, message.id, message.sender,
                             message.content, message.created_at),
                        )
                    await message.ack()
                    accepted += 1
                if page.next_after is None:
                    break
                after = page.next_after
            print(f"Accepted {accepted} pending event(s); archive: {path}")
    finally:
        archive.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8877")
    parser.add_argument("--credentials", default=".carrier/sdk/events.json")
    parser.add_argument("--archive", default=".carrier/sdk/event-archive.db")
    parser.add_argument("--page-size", type=int, choices=range(1, 101), metavar="1-100", default=50)
    asyncio.run(main(parser.parse_args()))
