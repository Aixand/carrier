"""Publish a build result with a stable event key that survives producer retries."""

import argparse
import asyncio

from carrier import Client, ConflictError, TransportError


async def main(args):
    key = f"build.finished:{args.build_id}"
    async with Client(url=args.url, credentials=args.credentials) as inbox:
        message = await inbox.send_json(
            {"type": "build.finished", "build_id": args.build_id, "status": args.status},
            to=args.to,
            idempotency_key=key,
        )
        status = await inbox.delivery_status(key)
        print(f"Message {message.id}: {status['status']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_id", help="Stable build ID, reused when retrying this event")
    parser.add_argument("--status", choices=("passed", "failed"), default="passed")
    parser.add_argument("--url", default="http://127.0.0.1:8877")
    parser.add_argument("--credentials", default=".carrier/sdk/requester.json")
    parser.add_argument("--to", default="sdk/build-events")
    try:
        asyncio.run(main(parser.parse_args()))
    except TransportError:
        raise SystemExit(
            "No response was confirmed; the event may already be stored. "
            "Rerun the same command with the same build ID, status, and recipient."
        ) from None
    except ConflictError:
        raise SystemExit(
            "This event key was already used with different content or routing. "
            "For a retry, restore the original arguments; use a new build ID "
            "only for a new build event."
        ) from None
